// Formatting for the suite UI (DESIGN.md 8.5: "the client does no float arithmetic on money").
//
// Every value arrives from the engine as an integer: prices in hundredths (2.5 -> 250), sizes and
// traded volume in pence, times in milliseconds, speeds in hundredths (1x -> 100). Each formatter
// takes such an integer and builds text with integer operations only (%, exact division of a
// multiple, string padding); a non-integer argument is a programming error and throws.

const MS_PER_DAY = 86400000;

export function isInt(value) {
  return Number.isSafeInteger(value);
}

function requireInt(value, name) {
  if (!Number.isSafeInteger(value)) {
    throw new TypeError(name + ' must be a safe integer');
  }
  return value;
}

// Floor division of a non-negative integer by a positive integer, exactly: a - a % b is a multiple
// of b, so the division has no remainder and no rounding.
export function idiv(a, b) {
  requireInt(a, 'dividend');
  requireInt(b, 'divisor');
  if (a < 0 || b <= 0) {
    throw new RangeError('idiv takes a >= 0 and b > 0');
  }
  return (a - (a % b)) / b;
}

function pad2(n) {
  return n < 10 ? '0' + String(n) : String(n);
}

// "1234567" -> "1,234,567" (string work only).
function group3(n) {
  const text = String(n);
  let out = '';
  for (let i = 0; i < text.length; i += 1) {
    const left = text.length - i;
    out += text[i];
    if (left > 1 && left % 3 === 1) {
      out += ',';
    }
  }
  return out;
}

// A price in hundredths as Betfair shows it: 250 -> "2.5", 345 -> "3.45", 1000 -> "10", 101 -> "1.01".
export function formatPrice(priceH) {
  requireInt(priceH, 'price_h');
  if (priceH <= 0) {
    throw new RangeError('price_h must be positive');
  }
  const whole = idiv(priceH, 100);
  const cents = priceH % 100;
  if (cents === 0) {
    return String(whole);
  }
  if (cents % 10 === 0) {
    return String(whole) + '.' + String(cents / 10);
  }
  return String(whole) + '.' + pad2(cents);
}

// A ladder or grid size in pence as whole pounds, half up: 1234 -> "12", 150 -> "2", 40 -> "<1",
// 0 -> "0", 12300000 -> "123k". The column header carries the currency.
export function formatSize(sizeP) {
  requireInt(sizeP, 'size_p');
  if (sizeP < 0) {
    throw new RangeError('size_p must not be negative');
  }
  if (sizeP === 0) {
    return '0';
  }
  const pounds = idiv(sizeP + 50, 100);
  if (pounds === 0) {
    return '<1';
  }
  if (pounds >= 100000) {
    return String(idiv(pounds, 1000)) + 'k';
  }
  return String(pounds);
}

// An exact amount in pence: 123456 -> "£1,234.56", -5 -> "-£0.05".
export function formatMoney(pence) {
  requireInt(pence, 'pence');
  const sign = pence < 0 ? '-' : '';
  const magnitude = pence < 0 ? -pence : pence;
  return sign + '£' + group3(idiv(magnitude, 100)) + '.' + pad2(magnitude % 100);
}

// Whole pounds, half up, for volumes: 1234550 -> "£12,346".
export function formatPounds(pence) {
  requireInt(pence, 'pence');
  if (pence < 0) {
    throw new RangeError('pence must not be negative');
  }
  return '£' + group3(idiv(pence + 50, 100));
}

// A replay speed in hundredths: 100 -> "1x", 25 -> "0.25x", 50 -> "0.5x", 1000 -> "10x".
export function formatSpeed(speedX100) {
  requireInt(speedX100, 'speed_x100');
  if (speedX100 <= 0) {
    throw new RangeError('speed_x100 must be positive');
  }
  const whole = idiv(speedX100, 100);
  const frac = speedX100 % 100;
  if (frac === 0) {
    return String(whole) + 'x';
  }
  const digits = frac % 10 === 0 ? String(frac / 10) : pad2(frac);
  return String(whole) + '.' + digits + 'x';
}

function clockText(totalSeconds) {
  const hours = idiv(totalSeconds, 3600);
  const minutes = idiv(totalSeconds % 3600, 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return String(hours) + ':' + pad2(minutes) + ':' + pad2(seconds);
  }
  return pad2(minutes) + ':' + pad2(seconds);
}

// The countdown to the scheduled off (DESIGN.md 8.2): before the off "T-09:58" (seconds rounded up,
// so it reads T-00:01 until the off), "soon" under 60 s and "imminent" under 30 s; after the
// scheduled off but before the in-play flip "T+00:05"; in play "IN-PLAY +00:12". Returns
// {text, level}, level one of unknown, normal, soon, imminent, past, inplay.
export function formatCountdown(msToOff, inplay) {
  if (msToOff === null || msToOff === undefined) {
    return { text: inplay ? 'IN-PLAY' : 'T --:--', level: inplay ? 'inplay' : 'unknown' };
  }
  requireInt(msToOff, 'ms_to_off');
  if (inplay) {
    const since = msToOff < 0 ? idiv(-msToOff, 1000) : 0;
    return { text: 'IN-PLAY +' + clockText(since), level: 'inplay' };
  }
  if (msToOff < 0) {
    return { text: 'T+' + clockText(idiv(-msToOff, 1000)), level: 'past' };
  }
  const seconds = idiv(msToOff + 999, 1000);
  let level = 'normal';
  if (msToOff < 30000) {
    level = 'imminent';
  } else if (msToOff < 60000) {
    level = 'soon';
  }
  return { text: 'T-' + clockText(seconds), level: level };
}

// Publisher time (epoch ms) as a UTC time of day, "14:05:12".
export function formatClockUtc(pt) {
  requireInt(pt, 'pt');
  if (pt < 0) {
    throw new RangeError('pt must not be negative');
  }
  const seconds = idiv(pt % MS_PER_DAY, 1000);
  return pad2(idiv(seconds, 3600)) + ':' + pad2(idiv(seconds % 3600, 60)) + ':' + pad2(seconds % 60);
}

// Codes from the engine are shown as they are only when they look like codes.
const CODE_RE = /^[a-z][a-z0-9_]{0,63}$/;

export function safeCode(value) {
  return typeof value === 'string' && CODE_RE.test(value) ? value : 'unlisted_code';
}

// The reserved synthetic namespace (docs/data-handling.md): market ids 1.999 plus six digits.
const SYNTHETIC_MARKET_RE = /^1\.999[0-9]{6}$/;

export function isSyntheticMarketId(value) {
  return typeof value === 'string' && SYNTHETIC_MARKET_RE.test(value);
}

const INVALID_REASON_TEXT = {
  non_finite_size: 'book invalid: non-finite size',
  stream_unreliable: '503: data possibly stale',
};

export function invalidReasonText(reason) {
  if (reason === null || reason === undefined) {
    return '';
  }
  const code = safeCode(reason);
  return Object.prototype.hasOwnProperty.call(INVALID_REASON_TEXT, code)
    ? INVALID_REASON_TEXT[code]
    : 'book invalid: ' + code;
}
