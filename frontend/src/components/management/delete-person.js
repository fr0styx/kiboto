// Deleting a person asks first what happens to their files (Users decision 7 b, SET-19): keep them
// in a renamed folder, give them to someone, or delete them. Then the usual confirmation, with the
// name typed; deleting the files makes the server ask the sharper question.
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { showBottomSheet, showConfirmToast } from '../../toast.js';

/** The query for the choice: {files: 'keep' | 'give' | 'delete', to?: username}. */
export function deleteQuery(choice) {
  if (choice.files === 'give') return `?files=give&give_to=${encodeURIComponent(choice.to || '')}`;
  return `?files=${choice.files === 'delete' ? 'delete' : 'keep'}`;
}

/** The question the last confirmation asks for this choice. */
export function deleteQuestion(choice, username) {
  if (choice.files === 'delete') return t('users.del_q_delete', 'Delete @{username} and all their files? This can\'t be undone.', { username });
  if (choice.files === 'give') return t('users.del_q_give', 'Delete @{username}? Their files go to {to}, in a folder named "From {username}".', { username, to: choice.to });
  return t('users.del_q_keep', 'Delete @{username}? Their files are kept in a folder renamed for them, so the name can be used again.', { username });
}

/** One sentence on what happened to the files, from the server's answer. */
export function filesDoneText(done) {
  if (!done || done.files === 'none') return '';
  if (done.files === 'given') return t('users.del_done_given', 'Their files are with {to} now.', { to: done.to });
  if (done.files === 'deleted') return t('users.del_done_deleted', 'Their files were deleted.');
  if (done.files === 'error') return t('users.del_done_error', 'Their files could not be handled: {error}', { error: done.error || '' });
  return t('users.del_done_kept', 'Their files are in {folder}.', { folder: String(done.where || '').split('/').pop() });
}

/** The choices, as sheet items: keep, give to each other person, delete. */
export function deleteChoices(username, others, onPick) {
  return [
    { icon: '📁', label: t('users.del_keep', 'Keep their files'), onClick: () => onPick({ files: 'keep' }) },
    ...others.map((name) => ({ icon: '🤝', label: t('users.del_give', 'Give their files to {name}', { name }), onClick: () => onPick({ files: 'give', to: name }) })),
    { icon: '🗑️', label: t('users.del_delete', 'Delete their files too'), destructive: true, onClick: () => onPick({ files: 'delete' }) },
  ];
}

/** Asks, then calls run(choice) once the deletion is confirmed. */
export async function askDeletePerson(user, run) {
  let others;
  try {
    const list = await api.get('/api/users');
    others = (list?.users || list || []).map((u) => u.username).filter((n) => n && n !== user.username);
  } catch {
    others = []; // keep and delete still work
  }
  const confirm = (choice) =>
    showConfirmToast(t('users.delete_title', 'Delete this person?'), deleteQuestion(choice, user.username), () => run(choice), null, {
      okText: t('users.delete_user', 'Delete User'),
      destructive: true,
      typeToConfirm: user.username,
    });
  showBottomSheet({
    title: t('users.del_title', 'What happens to the files of {name}?', { name: user.username }),
    subtitle: t('users.del_sub', 'Their account is deleted and they are signed out everywhere.'),
    items: deleteChoices(user.username, others, confirm),
  });
}
