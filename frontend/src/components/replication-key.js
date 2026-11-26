/**
 * A copy to another machine (Storage, Replication) signs in there with a key: on Kiboto OS the
 * machine's own replication key, elsewhere that of the user Kiboto runs as. The job form shows it,
 * to be added to the user on the other machine.
 */
import { api } from '../api.js';

/** Shows the key in the form, with its help; hidden when there is none. Returns the key. */
export async function showReplicationKey() {
  const help = document.getElementById('repl-key-help');
  const box = document.getElementById('repl-key');
  if (!help || !box) return '';
  let key;
  try {
    key = String((await api.get('/api/storage/replication/key'))?.public_key || '');
  } catch {
    key = ''; // an older server, or no right to see it: the form works without it
  }
  box.textContent = key;
  help.hidden = !key;
  box.hidden = !key;
  return key;
}
