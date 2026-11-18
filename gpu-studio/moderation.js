// Жёсткие запреты, которые действуют всегда.
const RULES = [
  { re: /\b(child|children|kid|kids|minor|minors|underage|under-age|teen|teens|preteen|toddler|infant|baby|loli|lolita|shota|schoolgirl|schoolboy|\d{1,2}\s*-?\s*(yo|y\.o\.|years?\s*old))\b|реб[её]н|дет(и|ей|ск)|малолет|несовершеннолет|школьни|подрост|девочк|мальчик|лоли/i,
    why: 'Запрещено: любые изображения с участием несовершеннолетних.' },
  { re: /\b(deepfake|deep fake|face ?swap)\b|дипфейк|подмен\w* лиц/i,
    why: 'Запрещено: дипфейки и подмена лица реальных людей.' },
];
const SEXUAL = /\b(nude|naked|nsfw|sex|porn|explicit|topless|lingerie|erotic)\b|голы|обнаж|секс|порн|эрот/i;
// Публичные люди: сексуальный/порочащий контент с ними запрещён.
const REAL_PERSON = /\b(celebrity|famous|actress|actor|singer|president|politician|instagram model|my (girlfriend|ex|wife|classmate|coworker|neighbor))\b|знаменит|актрис|актёр|певиц|президент|политик|мо(я|ю) (девушк|бывш|жен|одноклассниц|коллег|соседк)/i;

export function checkPrompt(prompt) {
  for (const r of RULES) if (r.re.test(prompt)) return r.why;
  if (SEXUAL.test(prompt) && REAL_PERSON.test(prompt))
    return 'Запрещено: откровенный контент с реальными людьми.';
  return null;
}
