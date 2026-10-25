/** "Notify by email" on the Share page: the choice and what the API gets. */
export const NOTE_MAX = 500

export interface NotifyChoice {
  notify: boolean
  message: string
}

/** What the API gets: no email when email isn't set up or the box is unticked. */
export function notifyBody(choice: NotifyChoice, smtpEnabled: boolean): { notify: boolean; message?: string } {
  const notify = smtpEnabled && choice.notify
  const message = choice.message.trim()
  return notify && message ? { notify, message } : { notify }
}
