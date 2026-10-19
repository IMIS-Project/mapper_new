import {
	Assessment,
	CallMade,
	CallReceived,
	Check,
	ContentCopy,
	ErrorOutline,
	ExpandMore,
	Send,
	SwapHoriz,
	Timer,
} from "@mui/icons-material";
import {
	Accordion,
	AccordionDetails,
	AccordionSummary,
	Alert,
	Box,
	Card,
	IconButton,
	LinearProgress,
	Skeleton,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useMemo, useState } from "react";

import MethodChip from "../common/MethodChip";
import { STATUS_TEXT, statusTone } from "../common/httpStatus";
import StatusChip from "../common/StatusChip";
import HeadersTable from "./HeadersTable";

function toPrettyJson(value) {
	if (value == null || value === "") return null;
	if (typeof value === "string") {
		const trimmed = value.trim();
		if (!trimmed) return null;
		try {
			return JSON.stringify(JSON.parse(trimmed), null, 2);
		} catch {
			return value;
		}
	}
	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return String(value);
	}
}

function countEntries(headers) {
	if (!headers) return 0;
	if (Array.isArray(headers)) return headers.length;
	if (typeof headers === "object") return Object.keys(headers).length;
	return 0;
}

function formatClock(timestamp) {
	if (!timestamp) return "";
	const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
	if (Number.isNaN(date.getTime())) return "";
	return date.toLocaleTimeString([], { hour12: false });
}

async function copyText(text) {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
		const helper = document.createElement("textarea");
		helper.value = text;
		helper.style.position = "fixed";
		helper.style.opacity = "0";
		document.body.appendChild(helper);
		helper.select();
		document.execCommand("copy");
		document.body.removeChild(helper);
		return true;
	} catch {
		return false;
	}
}

const TOKEN_REGEX =
	/("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false)\b|\b(null)\b/g;

function JsonBlock({
	value,
	emptyMessage = "Nothing captured for this stage.",
	maxHeight = 320,
}) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const codeFont = theme.typography.fontFamilyCode;
	const [copied, setCopied] = useState(false);

	const text = useMemo(() => toPrettyJson(value), [value]);

	const colors = useMemo(
		() => ({
			key: theme.palette.secondary.main,
			string: theme.palette.success.main,
			number: theme.palette.warning.main,
			boolean: theme.palette.info.main,
			muted: theme.palette.text.disabled,
		}),
		[theme],
	);

	const highlighted = useMemo(() => {
		if (!text) return null;
		const nodes = [];
		let lastIndex = 0;
		let cursor = 0;
		for (const match of text.matchAll(TOKEN_REGEX)) {
			const [full, stringToken, colon, numberToken, boolToken, nullToken] =
				match;
			if (match.index > lastIndex)
				nodes.push(text.slice(lastIndex, match.index));
			let color = theme.palette.text.primary;
			if (stringToken !== undefined) color = colon ? colors.key : colors.string;
			else if (numberToken !== undefined) color = colors.number;
			else if (boolToken !== undefined) color = colors.boolean;
			else if (nullToken !== undefined) color = colors.muted;
			nodes.push(
				<span key={`tok-${cursor}`} style={{ color }}>
					{full}
				</span>,
			);
			cursor += 1;
			lastIndex = match.index + full.length;
		}
		if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
		return nodes;
	}, [text, colors, theme.palette.text.primary]);

	const handleCopy = async () => {
		const ok = await copyText(text || "");
		if (ok) {
			setCopied(true);
			window.setTimeout(() => setCopied(false), 1500);
		}
	};

	if (!text) {
		return (
			<Box
				sx={{
					px: 1.5,
					py: 2,
					borderRadius: 2,
					border: "1px dashed",
					borderColor: "divider",
					textAlign: "center",
				}}
			>
				<Typography
					variant="body2"
					sx={{ color: "text.disabled", fontStyle: "italic" }}
				>
					{emptyMessage}
				</Typography>
			</Box>
		);
	}

	return (
		<Box
			sx={{
				position: "relative",
				borderRadius: 2,
				border: "1px solid",
				borderColor: "divider",
				overflow: "hidden",
				backgroundColor: alpha(
					theme.palette.text.primary,
					isDark ? 0.045 : 0.02,
				),
			}}
		>
			<Box sx={{ position: "absolute", top: 6, right: 6, zIndex: 2 }}>
				<Tooltip title={copied ? "Copied" : "Copy JSON"}>
					<IconButton
						size="small"
						aria-label="Copy JSON"
						onClick={handleCopy}
						sx={{
							border: "1px solid",
							borderColor: "divider",
							backgroundColor: alpha(theme.palette.background.paper, 0.9),
							"&:hover": { backgroundColor: theme.palette.background.paper },
						}}
					>
						{copied ? (
							<Check sx={{ fontSize: 14, color: "success.main" }} />
						) : (
							<ContentCopy sx={{ fontSize: 13, color: "text.secondary" }} />
						)}
					</IconButton>
				</Tooltip>
			</Box>
			<Box
				component="pre"
				sx={{
					m: 0,
					px: 1.75,
					py: 1.5,
					maxHeight,
					overflow: "auto",
					fontFamily: codeFont,
					fontSize: "0.76rem",
					lineHeight: 1.7,
					whiteSpace: "pre-wrap",
					wordBreak: "break-word",
				}}
			>
				{highlighted}
			</Box>
		</Box>
	);
}

function Panel({ icon, title, meta, defaultExpanded = false, children }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";

	return (
		<Accordion
			defaultExpanded={defaultExpanded}
			disableGutters
			elevation={0}
			sx={{
				mb: 1.25,
				border: "1px solid",
				borderColor: "divider",
				borderRadius: "12px !important",
				overflow: "hidden",
				backgroundColor: alpha(
					theme.palette.background.paper,
					isDark ? 0.55 : 0.85,
				),
				"&:before": { display: "none" },
			}}
		>
			<AccordionSummary
				expandIcon={<ExpandMore sx={{ fontSize: 20 }} />}
				sx={{
					minHeight: 46,
					px: 1.75,
					"& .MuiAccordionSummary-content": {
						my: 1,
						minWidth: 0,
						display: "flex",
						alignItems: "center",
						gap: 1.25,
					},
				}}
			>
				<Box
					sx={{
						display: "inline-flex",
						color: "text.secondary",
						"& svg": { fontSize: 18 },
					}}
				>
					{icon}
				</Box>
				<Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
					{title}
				</Typography>
				{meta ? (
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", fontSize: "0.55rem" }}
					>
						{meta}
					</Typography>
				) : null}
			</AccordionSummary>
			<AccordionDetails sx={{ px: 1.75, pt: 0.25, pb: 1.75 }}>
				{children}
			</AccordionDetails>
		</Accordion>
	);
}

function Fact({ label, children }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";

	return (
		<Box
			sx={{
				px: 1.5,
				py: 1.1,
				borderRadius: 2,
				border: "1px solid",
				borderColor: "divider",
				backgroundColor: alpha(
					theme.palette.text.primary,
					isDark ? 0.03 : 0.015,
				),
			}}
		>
			<Typography
				className="mono-label"
				sx={{ color: "text.disabled", fontSize: "0.5rem", mb: 0.6 }}
			>
				{label}
			</Typography>
			{children}
		</Box>
	);
}

function SubLabel({ children }) {
	return (
		<Typography
			className="mono-label"
			sx={{ color: "text.disabled", mt: 1.75, mb: 0.75 }}
		>
			{children}
		</Typography>
	);
}

function TimingRow({ label, value, max, color }) {
	const theme = useTheme();
	const percent =
		value != null && max > 0
			? Math.min(Math.max((value / max) * 100, 3), 100)
			: 0;

	return (
		<Box sx={{ mb: 1.4 }}>
			<Box
				sx={{
					display: "flex",
					alignItems: "baseline",
					justifyContent: "space-between",
					gap: 2,
				}}
			>
				<Typography variant="body2" sx={{ color: "text.secondary" }}>
					{label}
				</Typography>
				<Typography
					sx={{
						fontFamily: theme.typography.fontFamilyCode,
						fontSize: "0.78rem",
						fontWeight: 600,
					}}
				>
					{value != null ? `${value} ms` : "—"}
				</Typography>
			</Box>
			<Box
				sx={{
					mt: 0.6,
					height: 5,
					borderRadius: 3,
					overflow: "hidden",
					backgroundColor: alpha(color, 0.14),
				}}
			>
				<Box
					sx={{
						height: "100%",
						width: `${percent}%`,
						borderRadius: 3,
						backgroundColor: color,
						transition: "width 0.45s ease",
					}}
				/>
			</Box>
		</Box>
	);
}

function EmptyPrompt() {
	const theme = useTheme();

	return (
		<Box sx={{ py: { xs: 6, sm: 9 }, textAlign: "center" }}>
			<Box
				sx={{
					width: 56,
					height: 56,
					mx: "auto",
					mb: 2.25,
					display: "flex",
					alignItems: "center",
					justifyContent: "center",
					borderRadius: 3,
					border: "1px solid",
					borderColor: alpha(theme.palette.primary.main, 0.3),
					backgroundColor: alpha(theme.palette.primary.main, 0.08),
					color: "primary.main",
				}}
			>
				<Send sx={{ fontSize: 25 }} />
			</Box>
			<Typography variant="subtitle1" sx={{ mb: 0.75 }}>
				No call captured yet
			</Typography>
			<Typography
				variant="body2"
				sx={{ color: "text.secondary", maxWidth: 400, mx: "auto" }}
			>
				Build a request on the left and fire it through the gateway. Every
				header exchanged with the external API will appear here, in full.
			</Typography>
		</Box>
	);
}

export default function ResponseViewer({
	result,
	request,
	timestamp,
	callId,
	loading,
}) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const codeFont = theme.typography.fontFamilyCode;
	const { palette } = theme;

	const failed =
		Boolean(result) && (result.success === false || Boolean(result.error));
	const code = result?.status_code ?? null;
	const tone = statusTone(code, palette);

	const externalUrl =
		result?.external_url ??
		result?.external_request_url ??
		result?.target_url ??
		request?.targetUrl ??
		null;
	const externalMethod =
		result?.external_method ??
		result?.target_method ??
		request?.targetMethod ??
		null;

	const queryParams = useMemo(() => {
		const explicit =
			result?.external_query_params ?? result?.query_params ?? null;
		if (
			explicit &&
			typeof explicit === "object" &&
			!Array.isArray(explicit) &&
			Object.keys(explicit).length > 0
		) {
			return explicit;
		}
		if (typeof externalUrl !== "string" || !externalUrl.includes("?"))
			return null;
		try {
			const parsed = new URL(externalUrl);
			const pairs = {};
			parsed.searchParams.forEach((value, key) => {
				pairs[key] = value;
			});
			return Object.keys(pairs).length > 0 ? pairs : null;
		} catch {
			return null;
		}
	}, [result, externalUrl]);

	const internalBody =
		request?.requestData ??
		result?.request_body ??
		result?.internal_request_body ??
		null;
	const externalBody =
		result?.external_request_body ??
		result?.transformed_request_body ??
		result?.transformed_request ??
		null;

	const externalCode =
		result?.external_status_code ??
		result?.external_response?.status_code ??
		null;
	const externalTone = statusTone(externalCode, palette);

	const totalMs = result?.total_time_ms ?? result?.response_time_ms ?? null;
	const externalMs = result?.external_response_time_ms ?? null;
	const overheadMs =
		totalMs != null && externalMs != null
			? Math.max(totalMs - externalMs, 0)
			: null;
	const timingMax = Math.max(totalMs ?? 0, externalMs ?? 0, overheadMs ?? 0, 1);
	const hasTiming = totalMs != null || externalMs != null;

	const internalHeaderCount = countEntries(result?.request_headers);
	const externalHeaderCount = countEntries(result?.external_request_headers);
	const externalResponseHeaderCount = countEntries(
		result?.external_response_headers,
	);

	let content;

	if (loading && !result) {
		content = (
			<Box sx={{ pt: 1 }}>
				{[96, 52, 52].map((height, index) => (
					<Skeleton
						key={height + index}
						variant="rounded"
						height={height}
						sx={{ mb: 1.5, borderRadius: 2.5 }}
					/>
				))}
			</Box>
		);
	} else if (!result) {
		content = <EmptyPrompt />;
	} else {
		content = (
			<Box key={callId ?? "call"}>
				{}
				<Panel icon={<Assessment />} title="Overview" defaultExpanded>
					<Box sx={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
						<Box
							sx={{
								px: 2,
								py: 1.4,
								minWidth: 116,
								borderRadius: 2.5,
								textAlign: "center",
								border: "1px solid",
								borderColor: alpha(tone.color, 0.35),
								backgroundColor: alpha(tone.color, isDark ? 0.14 : 0.07),
							}}
						>
							<Typography
								sx={{
									fontFamily: codeFont,
									fontSize: "1.65rem",
									fontWeight: 700,
									lineHeight: 1.1,
									color: tone.color,
								}}
							>
								{code ?? "—"}
							</Typography>
							<Typography
								className="mono-label"
								sx={{ color: "text.secondary", fontSize: "0.5rem", mt: 0.5 }}
							>
								{tone.label}
							</Typography>
						</Box>

						<Box
							sx={{
								flex: "1 1 320px",
								minWidth: 260,
								display: "grid",
								gridTemplateColumns: "repeat(auto-fit, minmax(128px, 1fr))",
								gap: 1.25,
							}}
						>
							<Fact label="Outcome">
								<StatusChip status={failed ? "failed" : "success"} />
							</Fact>
							<Fact label="Round trip">
								<Typography
									sx={{
										fontFamily: codeFont,
										fontSize: "0.85rem",
										fontWeight: 600,
									}}
								>
									{result.response_time_ms != null
										? `${result.response_time_ms} ms`
										: "—"}
								</Typography>
							</Fact>
							<Fact label="Captured at">
								<Typography sx={{ fontFamily: codeFont, fontSize: "0.8rem" }}>
									{formatClock(timestamp) || "—"}
								</Typography>
							</Fact>
						</Box>
					</Box>
				</Panel>

				{}
				<Panel
					icon={<CallMade />}
					title="Internal request headers"
					meta={internalHeaderCount > 0 ? `${internalHeaderCount}` : undefined}
				>
					<HeadersTable
						headers={result.request_headers}
						emptyMessage="The gateway did not echo the headers sent to it."
					/>
				</Panel>

				{}
				<Panel icon={<Send />} title="Internal request body">
					<Typography
						variant="caption"
						sx={{ display: "block", color: "text.disabled", mb: 1 }}
					>
						Payload sent from this console to the gateway.
					</Typography>
					<JsonBlock
						value={internalBody}
						emptyMessage="No request body was sent."
					/>
				</Panel>

				{}
				<Panel
					icon={<SwapHoriz />}
					title="External request"
					meta={
						externalMethod ? String(externalMethod).toUpperCase() : undefined
					}
				>
					<Box
						sx={{
							display: "flex",
							alignItems: "center",
							gap: 1.25,
							flexWrap: "wrap",
						}}
					>
						{externalMethod ? <MethodChip method={externalMethod} /> : null}
						<Typography
							component="span"
							sx={{
								flex: 1,
								minWidth: 200,
								fontFamily: codeFont,
								fontSize: "0.76rem",
								wordBreak: "break-all",
							}}
						>
							{externalUrl || "External URL not echoed by the gateway."}
						</Typography>
						{externalUrl ? (
							<Tooltip title="Copy URL">
								<IconButton
									size="small"
									aria-label="Copy external URL"
									onClick={() => copyText(externalUrl)}
								>
									<ContentCopy sx={{ fontSize: 14, color: "text.secondary" }} />
								</IconButton>
							</Tooltip>
						) : null}
					</Box>

					<SubLabel>
						Forwarded headers
						{externalHeaderCount > 0 ? ` · ${externalHeaderCount}` : ""}
					</SubLabel>
					<HeadersTable
						headers={result.external_request_headers}
						emptyMessage="No headers were forwarded to the external API."
					/>

					<SubLabel>Query parameters</SubLabel>
					<HeadersTable
						headers={queryParams}
						emptyMessage="No query parameters on the external URL."
					/>

					<SubLabel>Transformed body</SubLabel>
					<JsonBlock
						value={externalBody}
						emptyMessage="The gateway did not echo the transformed body."
					/>
				</Panel>

				{}
				<Panel icon={<CallReceived />} title="External response">
					<Box
						sx={{ display: "flex", alignItems: "center", gap: 1.25, mb: 0.5 }}
					>
						{externalCode != null ? (
							<>
								<Box
									sx={{
										width: 9,
										height: 9,
										borderRadius: "50%",
										backgroundColor: externalTone.color,
										boxShadow: `0 0 0 3px ${alpha(externalTone.color, 0.22)}`,
									}}
								/>
								<Typography
									sx={{
										fontFamily: codeFont,
										fontSize: "0.92rem",
										fontWeight: 700,
										color: externalTone.color,
									}}
								>
									{externalCode}
									{STATUS_TEXT[externalCode]
										? ` · ${STATUS_TEXT[externalCode]}`
										: ""}
								</Typography>
							</>
						) : (
							<Typography variant="body2" sx={{ color: "text.disabled" }}>
								Target status code not available.
							</Typography>
						)}
					</Box>

					<SubLabel>
						Response headers
						{externalResponseHeaderCount > 0
							? ` · ${externalResponseHeaderCount}`
							: ""}
					</SubLabel>
					<HeadersTable
						headers={result.external_response_headers}
						emptyMessage="No response headers were recorded from the external API."
					/>

					<SubLabel>Response body</SubLabel>
					<JsonBlock
						value={result.data}
						emptyMessage="The external API returned an empty body."
						maxHeight={420}
					/>
				</Panel>

				{}
				<Panel icon={<Timer />} title="Timing">
					{hasTiming ? (
						<>
							<TimingRow
								label="Gateway round trip (total)"
								value={totalMs}
								max={timingMax}
								color={palette.primary.main}
							/>
							<TimingRow
								label="External call"
								value={externalMs}
								max={timingMax}
								color={palette.secondary.main}
							/>
							<TimingRow
								label="Mapping & transport overhead"
								value={overheadMs}
								max={timingMax}
								color={palette.info.main}
							/>
						</>
					) : (
						<Typography
							variant="body2"
							sx={{ color: "text.disabled", fontStyle: "italic" }}
						>
							No timing data was returned for this call.
						</Typography>
					)}
				</Panel>

				{}
				{failed ? (
					<Panel
						icon={<ErrorOutline />}
						title="Error"
						defaultExpanded
						meta={code != null ? `HTTP ${code}` : undefined}
					>
						<Alert
							severity="error"
							variant="outlined"
							icon={false}
							sx={{
								"& .MuiAlert-message": {
									fontFamily: codeFont,
									fontSize: "0.76rem",
									wordBreak: "break-word",
								},
							}}
						>
							{result.error ||
								"The gateway reported this call as failed without an error message."}
						</Alert>
						{result.status_code != null ? (
							<Typography
								variant="caption"
								sx={{ display: "block", mt: 1, color: "text.disabled" }}
							>
								The gateway itself responded with HTTP {result.status_code}.
							</Typography>
						) : null}
					</Panel>
				) : null}
			</Box>
		);
	}

	return (
		<Card
			elevation={0}
			sx={{
				display: "flex",
				flexDirection: "column",
				borderRadius: 3,
				border: "1px solid",
				borderColor: "divider",
				overflow: "hidden",
			}}
		>
			<Box
				sx={{
					px: 2.25,
					pt: 2,
					pb: 1.5,
					display: "flex",
					alignItems: "center",
					gap: 1.5,
					flexWrap: "wrap",
					borderBottom: "1px solid",
					borderColor: "divider",
				}}
			>
				<Box sx={{ flex: 1, minWidth: 200 }}>
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", fontSize: "0.55rem" }}
					>
						Response inspector
					</Typography>
					<Typography variant="subtitle1">
						Full request / response trail
					</Typography>
				</Box>
				{result ? (
					<StatusChip status={failed ? "failed" : "success"} size="small" />
				) : null}
				{timestamp ? (
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", fontSize: "0.55rem" }}
					>
						{formatClock(timestamp)}
					</Typography>
				) : null}
			</Box>

			{loading ? <LinearProgress sx={{ height: 3 }} /> : null}

			<Box sx={{ p: 2.25, pt: result ? 1.75 : 0, flex: 1 }}>{content}</Box>
		</Card>
	);
}
