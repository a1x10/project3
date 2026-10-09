// Разбор входящего сообщения WhatsApp в простой объект.
import { getContentType, isJidGroup, normalizeMessageContent } from 'baileys';

const IGNORED_TYPES = new Set(['protocolMessage', 'reactionMessage', 'pollUpdateMessage', 'senderKeyDistributionMessage', 'stickerMessage', 'keepInChatMessage', 'pinInChatMessage']);

function textOf(content) {
  if (!content) return '';
  return (
    content.conversation ||
    content.extendedTextMessage?.text ||
    content.imageMessage?.caption ||
    content.videoMessage?.caption ||
    content.documentMessage?.caption ||
    content.documentWithCaptionMessage?.message?.documentMessage?.caption ||
    ''
  ).trim();
}

export function parseMessage(msg) {
  if (!msg?.message || !msg.key?.remoteJid) return null;
  const content = normalizeMessageContent(msg.message);
  const type = getContentType(content);
  if (!type || IGNORED_TYPES.has(type)) return null;
  const inner = content[type] || {};
  const contextInfo = inner.contextInfo || null;
  const chat = msg.key.remoteJid;
  const isGroup = Boolean(isJidGroup(chat));

  let quoted = null;
  if (contextInfo?.quotedMessage) {
    const quotedContent = normalizeMessageContent(contextInfo.quotedMessage);
    const quotedType = getContentType(quotedContent);
    quoted = {
      id: contextInfo.stanzaId,
      participant: contextInfo.participant || null,
      message: contextInfo.quotedMessage,
      text: textOf(quotedContent),
      hasImage: quotedType === 'imageMessage',
      imageMime: quotedContent?.imageMessage?.mimetype || 'image/jpeg',
    };
  }

  return {
    id: msg.key.id,
    chat,
    isGroup,
    fromMe: Boolean(msg.key.fromMe),
    sender: isGroup ? msg.key.participant : chat,
    senderAlt: isGroup ? msg.key.participantAlt : msg.key.remoteJidAlt,
    name: (msg.pushName || '').trim(),
    type,
    text: textOf(content),
    hasImage: type === 'imageMessage',
    imageMime: content.imageMessage?.mimetype || 'image/jpeg',
    isVoice: type === 'audioMessage',
    audioSeconds: Number(content.audioMessage?.seconds || 0),
    audioMime: content.audioMessage?.mimetype || 'audio/ogg',
    mentions: contextInfo?.mentionedJid || [],
    quoted,
    timestamp: Number(msg.messageTimestamp || 0) * 1000,
    raw: msg,
  };
}
