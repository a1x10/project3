// Определение отправителя, админов и участников группы с учётом новых LID-идентификаторов WhatsApp.
import { areJidsSameUser, isLidUser, isPnUser, jidDecode, jidNormalizedUser } from 'baileys';

export function sameUser(a, b) {
  if (!a || !b) return false;
  return areJidsSameUser(jidNormalizedUser(a), jidNormalizedUser(b));
}

// Все известные идентификаторы отправителя (номер @s.whatsapp.net и/или @lid)
export function senderIds(ctx) {
  return [...new Set([ctx.sender, ctx.senderAlt].filter(Boolean).map((j) => jidNormalizedUser(j)))];
}

export async function senderPhone(ctx, sock) {
  for (const jid of senderIds(ctx)) {
    if (isPnUser(jid)) return jidDecode(jid)?.user || null;
  }
  const lid = senderIds(ctx).find((j) => isLidUser(j));
  if (lid && sock?.signalRepository?.lidMapping) {
    try {
      const pn = await sock.signalRepository.lidMapping.getPNForLID(lid);
      if (pn) return jidDecode(pn)?.user || null;
    } catch {
      /* сопоставление может быть ещё неизвестно */
    }
  }
  return null;
}

export function participantMatches(participant, ids) {
  const own = [participant.id, participant.lid, participant.phoneNumber].filter(Boolean);
  return own.some((p) => ids.some((id) => sameUser(p, id)));
}

export function findParticipant(meta, ids) {
  return (meta?.participants || []).find((p) => participantMatches(p, ids)) || null;
}

export function isBotJid(jid, me) {
  if (!jid || !me) return false;
  return sameUser(jid, me.id) || (me.lid ? sameUser(jid, me.lid) : false);
}
