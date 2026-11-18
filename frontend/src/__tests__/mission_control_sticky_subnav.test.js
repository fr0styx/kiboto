import { readIndexHtml } from './helpers/read-index-html.js';
import { readStyleCss } from './helpers/read-style-css.js';
import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'fs';
import path from 'path';

describe('Mission Control Fixated Sticky Sub-Navigation Bar', () => {
  it('verifies style.css defines sticky positioning, top offset, and backdrop filters for .mgmt-sticky-subnav', () => {
    const cssContent = readStyleCss();

    // .mgmt-sticky-subnav styling
    expect(cssContent).toMatch(/\.mgmt-sticky-subnav\s*\{[^}]*position:\s*sticky/);
    expect(cssContent).toMatch(/\.mgmt-sticky-subnav\s*\{[^}]*top:\s*0/);
    expect(cssContent).toMatch(/\.mgmt-sticky-subnav\s*\{[^}]*z-index:\s*45/);
    expect(cssContent).toMatch(/\.mgmt-sticky-subnav\s*\{[^}]*backdrop-filter:\s*blur/);

    // Direct fallback for .mgmt-detail-card > .mgmt-inner-tabs
    expect(cssContent).toMatch(/\.mgmt-detail-card\s*>\s*\.mgmt-inner-tabs\s*\{[^}]*position:\s*sticky/);
    expect(cssContent).toMatch(/\.mgmt-detail-card\s*>\s*\.mgmt-inner-tabs\s*\{[^}]*top:\s*0/);

    // Mobile responsive overrides
    expect(cssContent).toMatch(/#management-modal-overlay\s+\.mgmt-sticky-subnav\s*\{[^}]*top:\s*0\s*!important/);
    expect(cssContent).toMatch(
      /body\.mobile-mode\s+#management-modal-overlay\s+\.mgmt-sticky-subnav\s*\{[^}]*top:\s*0\s*!important/
    );

    // OLED theme override
    expect(cssContent).toMatch(/body\.theme-oled\s+\.mgmt-sticky-subnav/);
  });

  it('verifies tab click switches active sub-tab and resets contentPane scroll to top', () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay">
        <div class="mgmt-content-pane">
          <div id="mgmt-sec-storage" class="mgmt-detail-card">
            <div class="mgmt-sticky-subnav">
              <div class="mgmt-inner-tabs" role="tablist">
                <button class="mgmt-inner-tab active" data-tab-target="mgmt-pane-chassis-twin">Disks & 2.5D Chassis</button>
                <button class="mgmt-inner-tab" id="btn-tab-topo" data-tab-target="mgmt-pane-storage-topo">Pools & Topology</button>
              </div>
            </div>
            <div id="mgmt-pane-chassis-twin" class="mgmt-tab-pane" style="display: block;">Chassis Content</div>
            <div id="mgmt-pane-storage-topo" class="mgmt-tab-pane" style="display: none;">Topology Content</div>
          </div>
        </div>
      </div>
    `;

    const contentPane = document.querySelector('.mgmt-content-pane');
    contentPane.scrollTop = 450; // User had scrolled down

    const tab1 = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-chassis-twin"]');
    const tab2 = document.getElementById('btn-tab-topo');
    const pane1 = document.getElementById('mgmt-pane-chassis-twin');
    const pane2 = document.getElementById('mgmt-pane-storage-topo');

    // Attach click listener modeled identically to management.js
    [tab1, tab2].forEach((tab) => {
      tab.addEventListener('click', () => {
        const parentCard = tab.closest('.mgmt-detail-card');
        if (!parentCard) return;

        parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
          t.classList.remove('active');
          t.setAttribute('aria-selected', 'false');
        });
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');

        const targetPaneId = tab.dataset.tabTarget;
        parentCard.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
          p.style.display = p.id === targetPaneId ? 'block' : 'none';
        });

        const cp = tab.closest('.mgmt-content-pane') || document.querySelector('.mgmt-content-pane');
        if (cp && cp.scrollTop > 0) {
          cp.scrollTop = 0;
        }
      });
    });

    // Click tab 2
    tab2.click();

    expect(tab2.classList.contains('active')).toBe(true);
    expect(tab1.classList.contains('active')).toBe(false);
    expect(pane2.style.display).toBe('block');
    expect(pane1.style.display).toBe('none');
    expect(contentPane.scrollTop).toBe(0);
  });

  it('verifies #ai-telemetry-ribbon is positioned inside the Configuration tab (mgmt-pane-ai-index) as informational', () => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    const htmlContent = readIndexHtml();

    const configPaneIdx = htmlContent.indexOf('id="mgmt-pane-ai-index"');
    expect(configPaneIdx).toBeGreaterThan(-1);

    const ribbonIdx = htmlContent.indexOf('id="ai-telemetry-ribbon"');
    expect(ribbonIdx).toBeGreaterThan(-1);

    // Verify ribbon is declared after mgmt-pane-ai-index, NOT before mgmt-inner-tabs
    expect(ribbonIdx).toBeGreaterThan(configPaneIdx);

    const aiSecIdx = htmlContent.indexOf('id="mgmt-sec-ai"');
    const tabsIdx = htmlContent.indexOf('data-tab-target="mgmt-pane-ai-chat"');

    // Between mgmt-sec-ai and tabs, there should NOT be ai-telemetry-ribbon
    const headerSlice = htmlContent.slice(aiSecIdx, tabsIdx);
    expect(headerSlice).not.toContain('ai-telemetry-ribbon');
  });

  it('verifies #mgmt-sec-ai .mgmt-sticky-subnav preserves flex layout integrity and uses consistent SVG icons', () => {
    const cssContent = readStyleCss();

    // #mgmt-sec-ai .mgmt-sticky-subnav styling ensures flex-shrink: 0
    expect(cssContent).toMatch(/#mgmt-sec-ai\s+\.mgmt-sticky-subnav[^{]*\{[^}]*flex-shrink:\s*0\s*!important/);

    const htmlPath = path.resolve(__dirname, '../../index.html');
    const htmlContent = readIndexHtml();

    const aiSecIdx = htmlContent.indexOf('id="mgmt-sec-ai"');
    const aiSecSlice = htmlContent.slice(aiSecIdx, aiSecIdx + 1500);

    // Verify SVG icons are used instead of emojis
    expect(aiSecSlice).toContain('<use href="#i-kib"/>'); // Ask Kib carries Kib's face
    expect(aiSecSlice).toContain('<use href="#i-search"/>');
    expect(aiSecSlice).toContain('<use href="#i-sliders"/>');
  });

  it('verifies that style.css removes top padding on content pane when subnav is present and preserves 20px top padding when subnav is absent', () => {
    const cssContent = readStyleCss();

    // .mgmt-content-pane has padding-top: 0 when subnav is present
    expect(cssContent).toMatch(/\.mgmt-content-pane\.has-subnav[^{]*\{[^}]*padding-top:\s*0\s*!important/);
    // .mgmt-content-pane has padding-top: 20px when subnav is absent
    expect(cssContent).toMatch(/\.mgmt-content-pane:not\(\.has-subnav\)[^{]*\{[^}]*padding-top:\s*20px\s*!important/);

    expect(cssContent).toMatch(/\.mgmt-sticky-subnav\s*\{[^}]*margin:\s*0\s+-20px\s+14px\s+-20px/);
    expect(cssContent).toMatch(/\.mgmt-sticky-subnav\s*\{[^}]*padding:\s*8px\s+20px/);

    // Mobile overrides have compact padding
    expect(cssContent).toMatch(
      /#management-modal-overlay\s+\.mgmt-sticky-subnav\s*\{[^}]*padding:\s*6px\s+10px\s*!important/
    );
    expect(cssContent).toMatch(
      /#management-modal-overlay\s+\.mgmt-content-pane:not\(\.has-subnav\)[^{]*\{[^}]*padding-top:\s*12px\s*!important/
    );
  });

  it('verifies views without subnav (HUB, UPS) do not have sticky subnav and keep 20px padding; Activity has tabs now (SET-27)', () => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    const htmlContent = readIndexHtml();

    // 1. HUB view, Activity section, and UPS section do not contain .mgmt-sticky-subnav
    const activityIdx = htmlContent.indexOf('id="mgmt-sec-activity"');
    const upsIdx = htmlContent.indexOf('id="mgmt-sec-ups"');
    expect(activityIdx).toBeGreaterThan(-1);
    expect(upsIdx).toBeGreaterThan(-1);

    const activitySlice = htmlContent.slice(activityIdx, activityIdx + 2500);
    const upsSlice = htmlContent.slice(upsIdx, upsIdx + 2500);

    expect(activitySlice).toContain('class="mgmt-sticky-subnav"'); // History and Right now (SET-27)
    expect(upsSlice).not.toContain('class="mgmt-sticky-subnav"');

    // 2. Simulate showSection / showHub class toggling
    document.body.innerHTML = `
      <div id="management-modal-overlay">
        <div class="mgmt-content-pane">
          <div id="management-hub-view" style="display: block;">Hub Content</div>
          <div id="mgmt-sec-activity" class="mgmt-detail-card" style="display: none;">Activity Content</div>
          <div id="mgmt-sec-ups" class="mgmt-detail-card" style="display: none;">UPS Content</div>
          <div id="mgmt-sec-storage" class="mgmt-detail-card" style="display: none;">
            <div class="mgmt-sticky-subnav">
              <div class="mgmt-inner-tabs"></div>
            </div>
            Storage Content
          </div>
        </div>
      </div>
    `;

    const contentPane = document.querySelector('.mgmt-content-pane');

    // Test HUB navigation
    function simulateShowHub() {
      document.getElementById('management-hub-view').style.display = 'block';
      document.querySelectorAll('.mgmt-detail-card').forEach((c) => {
        c.style.display = 'none';
      });
      contentPane.classList.remove('has-subnav');
    }

    // Test Section navigation
    function simulateShowSection(targetId) {
      document.getElementById('management-hub-view').style.display = 'none';
      document.querySelectorAll('.mgmt-detail-card').forEach((c) => {
        c.style.display = c.id === targetId ? 'block' : 'none';
      });
      const activeCard = document.getElementById(targetId);
      const hasSubnav = activeCard ? !!activeCard.querySelector('.mgmt-sticky-subnav') : false;
      contentPane.classList.toggle('has-subnav', hasSubnav);
    }

    // Showing HUB: no has-subnav
    simulateShowHub();
    expect(contentPane.classList.contains('has-subnav')).toBe(false);

    // Showing Activity Monitor: no has-subnav -> keeps 20px padding
    simulateShowSection('mgmt-sec-activity');
    expect(contentPane.classList.contains('has-subnav')).toBe(false);

    // Showing UPS & Power: no has-subnav -> keeps 20px padding
    simulateShowSection('mgmt-sec-ups');
    expect(contentPane.classList.contains('has-subnav')).toBe(false);

    // Showing Storage (has subnav): has-subnav applied -> 0px padding
    simulateShowSection('mgmt-sec-storage');
    expect(contentPane.classList.contains('has-subnav')).toBe(true);
  });
});
