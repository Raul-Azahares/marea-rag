/**
 * Locate a citation's quote inside its fragment, ignoring case, accents, punctuation and
 * spacing: the same normalisation the backend uses to verify quotes
 * (app/text_utils.normalize_for_match). An approximate quote may not be found; the
 * fragment is then shown without a highlight.
 */

interface Normalized {
  text: string;
  /** For every character of `text`, its index in the original string. */
  sourceIndex: number[];
}

const LETTER_OR_DIGIT = /[\p{L}\p{N}]/u;
const COMBINING_MARK = /\p{M}/gu;

function normalizeWithMap(input: string): Normalized {
  let text = "";
  const sourceIndex: number[] = [];
  let pendingSpace = false;
  for (let i = 0; i < input.length; i++) {
    const folded = (input[i] ?? "").normalize("NFD").replace(COMBINING_MARK, "").toLowerCase();
    for (const char of folded) {
      if (LETTER_OR_DIGIT.test(char)) {
        if (pendingSpace && text.length > 0) {
          text += " ";
          sourceIndex.push(i);
        }
        text += char;
        sourceIndex.push(i);
        pendingSpace = false;
      } else {
        pendingSpace = true;
      }
    }
  }
  return { text, sourceIndex };
}

/** [start, end) range of the quote in `content`, or null when it is not found verbatim. */
export function findQuote(content: string, quote: string): [number, number] | null {
  const normalizedQuote = normalizeWithMap(quote).text;
  if (normalizedQuote.length < 3) return null;
  const haystack = normalizeWithMap(content);
  const at = haystack.text.indexOf(normalizedQuote);
  if (at < 0) return null;
  const start = haystack.sourceIndex[at];
  const end = haystack.sourceIndex[at + normalizedQuote.length - 1];
  if (start === undefined || end === undefined) return null;
  return [start, end + 1];
}

export interface Segment {
  text: string;
  highlighted: boolean;
}

export function highlightSegments(content: string, quote: string | undefined): Segment[] {
  const range = quote ? findQuote(content, quote) : null;
  if (!range) return [{ text: content, highlighted: false }];
  const [start, end] = range;
  return [
    { text: content.slice(0, start), highlighted: false },
    { text: content.slice(start, end), highlighted: true },
    { text: content.slice(end), highlighted: false },
  ].filter((segment) => segment.text.length > 0);
}
