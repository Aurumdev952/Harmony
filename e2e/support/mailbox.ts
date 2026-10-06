import { execFileSync } from 'child_process';

import { expect } from '@playwright/test';

import { PROJECT } from './env';

// The stack's mail sink (mailpit) sits on the internal network only, so the
// suite reads it through `docker exec` rather than publishing another port.
function mailpitContainer(): string {
  const id = execFileSync(
    'docker',
    [
      'ps',
      '-q',
      '--filter',
      `label=com.docker.compose.project=${PROJECT}`,
      '--filter',
      'label=com.docker.compose.service=mailpit',
    ],
    { encoding: 'utf8' },
  ).trim();
  if (!id) {
    throw new Error(`no mailpit container in ${PROJECT}`);
  }
  return id;
}

function mailpitApi<T>(path: string): T {
  const body = execFileSync(
    'docker',
    ['exec', mailpitContainer(), 'wget', '-qO-', `http://127.0.0.1:8025/api/v1/${path}`],
    { encoding: 'utf8' },
  );
  return JSON.parse(body) as T;
}

type Address = { Address: string };
type Summary = { Bcc: Address[] | null; ID: string; Subject: string; To: Address[] | null };
type Message = { HTML: string; Subject: string; Text: string };

/**
 * Waits for the newest message to `address` (To or Bcc: dashboard shares
 * blind-copy their recipients) whose subject matches, and returns it.
 * Addresses are unique per test, so earlier runs never match.
 */
export async function latestMail(
  address: string,
  subject: RegExp,
  timeout = 30_000,
): Promise<Message> {
  let found: Summary | undefined;
  await expect
    .poll(
      () => {
        const { messages } = mailpitApi<{ messages: Summary[] }>('messages?limit=500');
        found = messages.find(
          message =>
            [...(message.To ?? []), ...(message.Bcc ?? [])].some(to => to.Address === address) &&
            subject.test(message.Subject),
        );
        return found !== undefined;
      },
      { message: `mail to ${address} matching ${subject}`, timeout },
    )
    .toBe(true);
  return mailpitApi<Message>(`message/${found!.ID}`);
}

/** The first link in a message's HTML whose path matches. */
export function linkIn(message: Message, path: RegExp): string {
  const links = [...message.HTML.matchAll(/href="([^"]+)"/g)].map(match =>
    match[1].replace(/&amp;/g, '&'),
  );
  const link = links.find(href => path.test(new URL(href, 'http://x').pathname));
  if (!link) {
    throw new Error(`no link matching ${path} in "${message.Subject}": ${links.join(' ')}`);
  }
  return link;
}
