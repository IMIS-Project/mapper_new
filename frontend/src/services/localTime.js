/**
 * Display timestamps in the mapper host's local wall clock.
 *
 * Backend timestamps now carry an explicit local offset (for example
 * `2026-10-20T19:23:18+05:00`).  Parsing them with `Date` and then calling
 * `toLocaleString()` would re-render them in the viewer's browser timezone.
 * These helpers keep the date/time components exactly as the server wrote
 * them, while still using the real instant for relative labels and sorting.
 */

const MONTHS = [
	"Jan",
	"Feb",
	"Mar",
	"Apr",
	"May",
	"Jun",
	"Jul",
	"Aug",
	"Sep",
	"Oct",
	"Nov",
	"Dec",
];

const ISO_PARTS =
	/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$/i;

const pad = (value, length = 2) => String(value).padStart(length, "0");

function partsFromDate(date) {
	return {
		year: date.getFullYear(),
		month: date.getMonth() + 1,
		day: date.getDate(),
		hour: date.getHours(),
		minute: date.getMinutes(),
		second: date.getSeconds(),
		millisecond: date.getMilliseconds(),
	};
}

function parseTimestamp(value) {
	if (value === null || value === undefined || value === "") return null;

	if (value instanceof Date) {
		if (Number.isNaN(value.getTime())) return null;
		return { ...partsFromDate(value), instant: value.getTime() };
	}

	if (typeof value === "number") {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return null;
		return { ...partsFromDate(date), instant: date.getTime() };
	}

	const text = String(value).trim();
	const match = text.match(ISO_PARTS);
	if (match) {
		const [, year, month, day, hour, minute, second, fraction] = match;
		const instant = Date.parse(text);
		return {
			year: Number(year),
			month: Number(month),
			day: Number(day),
			hour: Number(hour),
			minute: Number(minute),
			second: Number(second),
			millisecond: fraction ? Number(`${fraction}000`.slice(0, 3)) : 0,
			instant: Number.isNaN(instant) ? null : instant,
		};
	}

	const date = new Date(text);
	if (Number.isNaN(date.getTime())) return null;
	return { ...partsFromDate(date), instant: date.getTime() };
}

const fallback = (value, empty = "—") => (value ? String(value) : empty);

export const formatDate = (value) => {
	const parts = parseTimestamp(value);
	if (!parts) return fallback(value);
	return `${MONTHS[parts.month - 1]} ${pad(parts.day)}, ${parts.year}, ${pad(
		parts.hour,
	)}:${pad(parts.minute)}`;
};

/** Full timestamp down to the second, for run history. */
export const formatExactTime = (value) => {
	const parts = parseTimestamp(value);
	if (!parts) return fallback(value);
	return `${MONTHS[parts.month - 1]} ${pad(parts.day)}, ${parts.year}, ${pad(
		parts.hour,
	)}:${pad(parts.minute)}:${pad(parts.second)}`;
};

/** Millisecond precision as the mapper host recorded it (no UTC suffix). */
export const formatPreciseTime = (value) => {
	const parts = parseTimestamp(value);
	if (!parts) return fallback(value);
	return `${parts.year}-${pad(parts.month)}-${pad(parts.day)} ${pad(
		parts.hour,
	)}:${pad(parts.minute)}:${pad(parts.second)}.${pad(parts.millisecond, 3)}`;
};

/** Coarse "how long ago" label, e.g. "just now", "12m ago", "3d ago". */
export const formatRelative = (value) => {
	const parts = parseTimestamp(value);
	if (!parts || parts.instant === null) return "—";
	const seconds = Math.max(0, Math.floor((Date.now() - parts.instant) / 1000));
	if (seconds < 45) return "just now";
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 30) return `${days}d ago`;
	return `${MONTHS[parts.month - 1]} ${pad(parts.day)}, ${parts.year}`;
};

/** Time only, e.g. the Recent calls clock in the Bank and Gateway pages. */
export const formatClock = (value) => {
	const parts = parseTimestamp(value);
	if (!parts) return "";
	return `${pad(parts.hour)}:${pad(parts.minute)}:${pad(parts.second)}`;
};

/** Split timestamp for the Call Logs table's two-line cell. */
export const formatLogTimestamp = (value) => {
	if (!value) return { date: "—", time: "" };
	const parts = parseTimestamp(value);
	if (!parts) return { date: String(value), time: "" };
	return {
		date: `${pad(parts.day)} ${MONTHS[parts.month - 1]} ${parts.year}`,
		time: `${pad(parts.hour)}:${pad(parts.minute)}:${pad(parts.second)}`,
	};
};

/** Full timestamp used by the Call Log detail header. */
export const formatLogDateTime = (value) => {
	const parts = parseTimestamp(value);
	if (!parts) return fallback(value);
	return `${parts.year}-${pad(parts.month)}-${pad(parts.day)} ${pad(
		parts.hour,
	)}:${pad(parts.minute)}:${pad(parts.second)}`;
};

export const timestampMillis = (value) => {
	const parts = parseTimestamp(value);
	return parts?.instant ?? 0;
};
