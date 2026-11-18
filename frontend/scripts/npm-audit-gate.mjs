// The npm side of the vulnerability gate (ARC-32): high and critical advisories fail the build.
//
// One kind of exception, each named below: an advisory with no fixed release yet that reaches only
// build and test tools (devDependencies), never what the image ships. It ends by itself: as soon as
// the package publishes a version newer than the one we had when the exception was made, the gate
// fails again, so the fix is taken. Run: node frontend/scripts/npm-audit-gate.mjs
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export const EXCEPTIONS = {
  // picomatch ReDoS (17 Nov 2026): every picomatch version is affected; it reaches vite, vitest and
  // the coverage tool only. Owner's decision: a narrow exception until picomatch ships a fix.
  'GHSA-fc5q-39xc-vjpf': { package: 'picomatch', latestWhenAllowed: '4.0.7' },
};
const SERIOUS = new Set(['high', 'critical']);

/** The advisory id of an audit "via" entry (its GitHub advisory URL ends with it). */
export const advisoryId = (via) =>
  String(via.url || '')
    .split('/')
    .pop();

/** "1.2.10" > "1.2.9": compares dotted versions number by number. */
export function newer(a, b) {
  const pa = String(a).split('.').map(Number);
  const pb = String(b).split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  }
  return false;
}

/**
 * What fails the gate.
 * @param {any} audit `npm audit --json`
 * @param {Set<string>} shipped package names in the production tree (`npm ls --omit=dev --all`)
 * @param {Record<string, string>} latest the newest published version of each excepted package
 * @param {Record<string, {package: string, latestWhenAllowed: string}>} exceptions
 * @returns {string[]} one line per problem; empty when the gate passes
 */
export function problems(audit, shipped, latest, exceptions = EXCEPTIONS) {
  const vulns = (audit && audit.vulnerabilities) || {};
  const out = [];
  const live = new Set();
  for (const [id, ex] of Object.entries(exceptions)) {
    if (latest[ex.package] && newer(latest[ex.package], ex.latestWhenAllowed)) {
      out.push(`${id}: ${ex.package} ${latest[ex.package]} is out; update it and remove the exception`);
    } else {
      live.add(id);
    }
  }
  // every advisory a package reaches, itself or through what it depends on (dependency cycles are fine)
  const reached = (name, seen = new Set()) => {
    if (seen.has(name)) return [];
    seen.add(name);
    return ((vulns[name] && vulns[name].via) || []).flatMap((via) =>
      typeof via === 'string' ? reached(via, seen) : [advisoryId(via)]
    );
  };
  const excused = new Set(
    Object.keys(vulns).filter((name) => {
      const ids = reached(name);
      return ids.length > 0 && ids.every((id) => live.has(id));
    })
  );
  for (const [name, v] of Object.entries(vulns)) {
    if (!SERIOUS.has(v.severity)) continue;
    if (!excused.has(name))
      out.push(`${name}: ${v.severity} (${(v.via || []).map((x) => (typeof x === 'string' ? x : x.url)).join(', ')})`);
    else if (shipped.has(name))
      out.push(`${name}: excused advisory but it ships (production dependency); no exception for that`);
  }
  return out;
}

function shippedNames() {
  const tree = JSON.parse(
    execFileSync('npm', ['ls', '--omit=dev', '--all', '--json'], { encoding: 'utf8', maxBuffer: 64 << 20 })
  );
  const names = new Set();
  const walk = (deps) => {
    for (const [name, d] of Object.entries(deps || {})) {
      names.add(name);
      walk(d.dependencies);
    }
  };
  walk(tree.dependencies);
  return names;
}

function auditJson() {
  try {
    return JSON.parse(execFileSync('npm', ['audit', '--json'], { encoding: 'utf8', maxBuffer: 64 << 20 }));
  } catch (e) {
    return JSON.parse(e.stdout); // npm audit exits 1 when it finds anything
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const latest = {};
  for (const ex of Object.values(EXCEPTIONS)) {
    latest[ex.package] = execFileSync('npm', ['view', ex.package, 'version'], { encoding: 'utf8' }).trim();
  }
  const found = problems(auditJson(), shippedNames(), latest);
  if (found.length) {
    console.error(`npm audit gate: ${found.length} problem(s)\n` + found.map((l) => `  ${l}`).join('\n'));
    process.exit(1);
  }
  console.log(
    `npm audit gate: no high or critical advisory (${Object.keys(EXCEPTIONS).length} named exception(s) for build tools)`
  );
}
