import {
	CallReceived,
	ContentCopy,
	ErrorOutline,
	InfoOutlined,
	NorthEast,
	SouthWest,
} from "@mui/icons-material";
import {
	Accordion,
	AccordionDetails,
	AccordionSummary,
	Alert,
	Box,
	Button,
	Chip,
	CircularProgress,
	IconButton,
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableRow,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useMemo } from "react";
import { useSnackbar } from "../../context/SnackbarContext";
import { useApiQuery } from "../../hooks/useApi";
import { formatLogDateTime } from "../../services/localTime";
import logService from "../../services/logService";
import MethodChip from "../common/MethodChip";
import StatusChip from "../common/StatusChip";

async function copyText(text) {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {}
	try {
		const area = document.createElement("textarea");
		area.value = text;
		area.style.position = "fixed";
		area.style.opacity = "0";
		document.body.appendChild(area);
		area.select();
		const ok = document.execCommand("copy");
		document.body.removeChild(area);
		return ok;
	} catch {
		return false;
	}
}

const isEmptyValue = (value) => {
	if (value === null || value === undefined) return true;
	if (typeof value === "string") return value.trim() === "";
	if (Array.isArray(value)) return value.length === 0;
	if (typeof value === "object") return Object.keys(value).length === 0;
	return false;
};

function formatBody(value) {
	if (isEmptyValue(value)) return null;
	if (typeof value === "string") {
		const trimmed = value.trim();
		try {
			return JSON.stringify(JSON.parse(trimmed), null, 2);
		} catch {
			return trimmed;
		}
	}
	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return String(value);
	}
}

function toEntries(map) {
	if (!map || typeof map !== "object") return [];
	return Object.entries(map).map(([name, value]) => {
		let display;
		if (value === null || value === undefined) display = "—";
		else if (Array.isArray(value))
			display = value.map((v) => String(v)).join(", ");
		else if (typeof value === "object") display = JSON.stringify(value);
		else display = String(value);
		return [name, display];
	});
}

function formatMs(value) {
	if (value === null || value === undefined) return "—";
	return `${Number(value).toLocaleString("en-US")} ms`;
}

function timeColor(ms, theme) {
	if (ms === null || ms === undefined) return theme.palette.text.disabled;
	if (ms < 200) return theme.palette.success.main;
	if (ms < 1000) return theme.palette.warning.main;
	return theme.palette.error.main;
}

function codeColor(code, theme) {
	if (code === null || code === undefined) return theme.palette.text.disabled;
	if (code < 300) return theme.palette.success.main;
	if (code < 400) return theme.palette.info.main;
	if (code < 500) return theme.palette.warning.main;
	return theme.palette.error.main;
}

function deriveError(detail, isFailed) {
	const internal = detail.internal_api_client_response;
	if (internal && typeof internal === "object" && internal.error) {
		return String(internal.error);
	}

	const response = detail.external_response;
	if (response && typeof response === "object") {
		if (response.error) return String(response.error);
		if (Array.isArray(response.detail)) {
			return response.detail
				.map((entry) =>
					entry && entry.loc && entry.msg
						? `${entry.loc.join(" -> ")}: ${entry.msg}`
						: JSON.stringify(entry),
				)
				.join("; ");
		}
		if (typeof response.detail === "string") return response.detail;
		if (response.message) return String(response.message);
	}

	if (isFailed) {
		return detail.external_status_code
			? `Upstream responded with HTTP ${detail.external_status_code}.`
			: "The call failed before an upstream response was recorded.";
	}
	return null;
}

function EmptyNote({ text }) {
	return (
		<Typography
			variant="caption"
			sx={{
				display: "block",
				px: 1.25,
				py: 1,
				borderRadius: 1.5,
				border: "1px dashed",
				borderColor: "divider",
				color: "text.disabled",
				fontStyle: "italic",
			}}
		>
			{text}
		</Typography>
	);
}

function CopyButton({ text, label, onCopied, sx }) {
	const { showSnackbar } = useSnackbar();

	const handleCopy = async () => {
		const ok = await copyText(text);
		if (ok) {
			showSnackbar(label || "Copied to clipboard", "success");
			onCopied?.();
		} else {
			showSnackbar("Copy failed — select the text manually.", "warning");
		}
	};

	return (
		<Tooltip title="Copy to clipboard" arrow>
			<IconButton
				size="small"
				onClick={handleCopy}
				sx={{ color: "text.disabled", ...sx }}
			>
				<ContentCopy sx={{ fontSize: 15 }} />
			</IconButton>
		</Tooltip>
	);
}

function KeyValueTable({ map, nameLabel = "Header", emptyText }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const rows = useMemo(() => toEntries(map), [map]);
	const { showSnackbar } = useSnackbar();

	if (!rows.length)
		return <EmptyNote text={emptyText || "Nothing captured."} />;

	const headSx = {
		fontFamily: theme.typography.fontFamilyCode,
		fontSize: "0.62rem",
		letterSpacing: "0.1em",
		textTransform: "uppercase",
		color: "text.disabled",
		borderBottom: "1px solid",
		borderColor: "divider",
		py: 0.9,
		px: 1.25,
		whiteSpace: "nowrap",
	};

	const cellSx = {
		fontFamily: theme.typography.fontFamilyCode,
		fontSize: "0.73rem",
		lineHeight: 1.55,
		borderBottom: "1px solid",
		borderColor: "divider",
		px: 1.25,
		py: 0.85,
		verticalAlign: "top",
	};

	return (
		<Box
			sx={{
				border: "1px solid",
				borderColor: "divider",
				borderRadius: 2,
				overflow: "hidden",
				backgroundColor: isDark ? alpha("#050c19", 0.4) : alpha("#ffffff", 0.5),
			}}
		>
			<Table size="small" sx={{ tableLayout: "fixed" }}>
				<TableHead>
					<TableRow>
						<TableCell sx={{ ...headSx, width: { xs: "40%", md: "32%" } }}>
							{nameLabel}
						</TableCell>
						<TableCell sx={headSx}>Value</TableCell>
						<TableCell sx={{ ...headSx, width: 44, p: 0 }} />
					</TableRow>
				</TableHead>
				<TableBody>
					{rows.map(([name, value]) => (
						<TableRow
							key={name}
							sx={{
								"&:nth-of-type(odd)": {
									backgroundColor: alpha(
										theme.palette.text.primary,
										isDark ? 0.035 : 0.018,
									),
								},
								"&:hover .kv-copy": { opacity: 1 },
								"&:last-of-type td": { borderBottom: 0 },
							}}
						>
							<TableCell
								sx={{
									...cellSx,
									fontWeight: 600,
									color: "text.secondary",
									wordBreak: "break-word",
								}}
							>
								{name}
							</TableCell>
							<TableCell
								sx={{
									...cellSx,
									wordBreak: "break-word",
									whiteSpace: "pre-wrap",
								}}
							>
								{value}
							</TableCell>
							<TableCell
								sx={{ ...cellSx, width: 44, px: 0.5, verticalAlign: "middle" }}
							>
								<IconButton
									className="kv-copy"
									size="small"
									aria-label={`Copy ${name}`}
									onClick={async () => {
										const ok = await copyText(value);
										showSnackbar(
											ok
												? `Copied “${name}”`
												: "Copy failed — select the text manually.",
											ok ? "success" : "warning",
										);
									}}
									sx={{
										color: "text.disabled",
										opacity: { xs: 1, md: 0 },
										transition: "opacity 0.15s ease",
										"&:hover": { color: "primary.main" },
									}}
								>
									<ContentCopy sx={{ fontSize: 14 }} />
								</IconButton>
							</TableCell>
						</TableRow>
					))}
				</TableBody>
			</Table>
		</Box>
	);
}

function JsonBlock({ value, emptyText = "No body captured for this call." }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const text = useMemo(() => formatBody(value), [value]);

	if (text === null) return <EmptyNote text={emptyText} />;

	return (
		<Box sx={{ position: "relative" }}>
			<Box sx={{ position: "absolute", top: 6, right: 8, zIndex: 1 }}>
				<CopyButton
					text={text}
					label="Body copied"
					sx={{
						backgroundColor: alpha(theme.palette.background.paper, 0.7),
						"&:hover": {
							backgroundColor: alpha(theme.palette.background.paper, 0.95),
						},
					}}
				/>
			</Box>
			<Box
				component="pre"
				sx={{
					m: 0,
					p: 1.75,
					pr: 5.5,
					borderRadius: 2,
					border: "1px solid",
					borderColor: "divider",
					backgroundColor: isDark
						? alpha("#050c19", 0.55)
						: alpha("#f6f9fd", 0.9),
					fontFamily: theme.typography.fontFamilyCode,
					fontSize: "0.74rem",
					lineHeight: 1.7,
					color: "text.primary",
					overflow: "auto",
					maxHeight: 400,
					whiteSpace: "pre-wrap",
					wordBreak: "break-word",
				}}
			>
				{text}
			</Box>
		</Box>
	);
}

function BlockLabel({ children, right }) {
	return (
		<Box
			sx={{
				display: "flex",
				alignItems: "center",
				justifyContent: "space-between",
				gap: 1,
				mt: 1.5,
				mb: 0.75,
			}}
		>
			<Typography
				className="mono-label"
				sx={{ color: "text.disabled", fontSize: "0.56rem" }}
			>
				{children}
			</Typography>
			{right}
		</Box>
	);
}

function DetailField({ label, children, mono = false, wide = false }) {
	const theme = useTheme();

	return (
		<Box
			sx={{
				minWidth: 0,
				gridColumn: wide ? { xs: "auto", lg: "span 2" } : "auto",
			}}
		>
			<Typography
				className="mono-label"
				sx={{ color: "text.disabled", fontSize: "0.52rem", mb: 0.4 }}
			>
				{label}
			</Typography>
			<Box
				sx={{
					fontFamily: mono ? theme.typography.fontFamilyCode : "inherit",
					fontSize: mono ? "0.74rem" : "0.84rem",
					fontWeight: mono ? 500 : 600,
					color: "text.primary",
					wordBreak: "break-all",
					display: "flex",
					alignItems: "center",
					gap: 0.5,
					minHeight: 22,
				}}
			>
				{children}
			</Box>
		</Box>
	);
}

function SectionAccordion({
	step,
	title,
	subtitle,
	icon,
	accent,
	badge,
	children,
}) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";

	return (
		<Accordion
			defaultExpanded
			disableGutters
			elevation={0}
			sx={{
				border: "1px solid",
				borderColor: "divider",
				borderRadius: "12px !important",
				backgroundImage: "none",
				backgroundColor: alpha(theme.palette.background.paper, 0.62),
				mb: 1.25,
				"&::before": { display: "none" },
				"&.Mui-expanded": { my: 0, mb: 1.25 },
			}}
		>
			<AccordionSummary
				expandIcon={<ExpandMoreIcon />}
				sx={{
					px: 1.75,
					minHeight: 50,
					"& .MuiAccordionSummary-content": {
						my: 1,
						alignItems: "center",
						gap: 1.25,
						minWidth: 0,
						overflow: "hidden",
					},
				}}
			>
				<Box
					sx={{
						width: 26,
						height: 26,
						flexShrink: 0,
						borderRadius: "8px",
						display: "flex",
						alignItems: "center",
						justifyContent: "center",
						color: isDark ? alpha(accent, 0.9) : accent,
						backgroundColor: alpha(accent, isDark ? 0.16 : 0.09),
						border: `1px solid ${alpha(accent, 0.32)}`,
						"& svg": { fontSize: 15 },
					}}
				>
					{icon}
				</Box>

				<Typography
					className="mono-label"
					sx={{ color: "text.disabled", fontSize: "0.55rem", flexShrink: 0 }}
				>
					{step}
				</Typography>

				<Typography
					variant="subtitle2"
					sx={{ fontWeight: 600, whiteSpace: "nowrap" }}
				>
					{title}
				</Typography>

				{subtitle ? (
					<Typography
						variant="caption"
						sx={{
							display: { xs: "none", sm: "block" },
							fontFamily: theme.typography.fontFamilyCode,
							fontSize: "0.66rem",
							color: "text.disabled",
							whiteSpace: "nowrap",
							overflow: "hidden",
							textOverflow: "ellipsis",
						}}
					>
						{subtitle}
					</Typography>
				) : null}

				<Box sx={{ flex: 1, minWidth: 8 }} />
				{badge}
			</AccordionSummary>

			<AccordionDetails
				sx={{
					px: 1.75,
					pt: 1.25,
					pb: 2,
					borderTop: "1px dashed",
					borderColor: "divider",
				}}
			>
				{children}
			</AccordionDetails>
		</Accordion>
	);
}

function ExpandMoreIcon() {
	return (
		<Box
			className="section-chevron"
			component="span"
			sx={{
				display: "inline-flex",
				color: "text.disabled",
				transition: "transform 0.22s ease",
				"& svg": { fontSize: 18 },
			}}
		>
			<svg
				viewBox="0 0 24 24"
				width="18"
				height="18"
				fill="currentColor"
				aria-hidden
			>
				<path d="M16.59 8.59 12 13.17 7.41 8.59 6 10l6 6 6-6z" />
			</svg>
		</Box>
	);
}

function CountBadge({ children }) {
	const theme = useTheme();

	return (
		<Chip
			size="small"
			label={children}
			sx={{
				height: 22,
				flexShrink: 0,
				fontFamily: theme.typography.fontFamilyCode,
				fontSize: "0.64rem",
				color: "text.secondary",
				backgroundColor: (t) => alpha(t.palette.text.primary, 0.05),
				border: "1px solid",
				borderColor: "divider",
				"& .MuiChip-label": { px: 1 },
			}}
		/>
	);
}

export default function LogDetail({ logId }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";

	const {
		data: detail,
		isLoading,
		isError,
		error,
		refetch,
	} = useApiQuery(["call-log", logId], () => logService.getLogDetail(logId), {
		staleTime: 15_000,
	});

	const isFailed = useMemo(() => {
		if (!detail) return false;
		const status = String(detail.status || "").toLowerCase();
		if (status === "failed" || status === "error" || status === "failure")
			return true;
		if ((detail.external_status_code ?? 0) >= 400) return true;
		return detail.overall_status === false;
	}, [detail]);

	const errorMessage = useMemo(
		() => (detail && isFailed ? deriveError(detail, isFailed) : null),
		[detail, isFailed],
	);

	const shellSx = {
		px: { xs: 1.5, md: 2.25 },
		py: 2,
		borderTop: "2px solid",
		borderTopColor: alpha(theme.palette.primary.main, 0.35),
		backgroundColor: alpha(theme.palette.primary.main, isDark ? 0.035 : 0.02),
	};

	if (isLoading) {
		return (
			<Box
				sx={{
					...shellSx,
					display: "flex",
					alignItems: "center",
					justifyContent: "center",
					gap: 1.5,
					py: 4,
				}}
			>
				<CircularProgress size={18} thickness={5} />
				<Typography className="mono-label" sx={{ color: "text.secondary" }}>
					Fetching full log
				</Typography>
			</Box>
		);
	}

	if (isError || !detail) {
		const message =
			error?.response?.data?.detail ||
			error?.message ||
			"The full log could not be loaded.";
		return (
			<Box sx={shellSx}>
				<Alert
					severity="error"
					action={
						<Button color="inherit" size="small" onClick={() => refetch()}>
							Retry
						</Button>
					}
				>
					{typeof message === "string"
						? message
						: "The full log could not be loaded."}
				</Alert>
			</Box>
		);
	}

	const headerCount = (map) => toEntries(map).length;

	return (
		<Box sx={shellSx}>
			{}
			<SectionAccordion
				step="01"
				title="Overview"
				subtitle="call summary"
				icon={<InfoOutlined />}
				accent={theme.palette.primary.main}
				badge={
					<StatusChip
						status={detail.status || (isFailed ? "failed" : "success")}
					/>
				}
			>
				<Box
					sx={{
						display: "grid",
						gap: 1.75,
						gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(3, 1fr)" },
						mt: 0.5,
					}}
				>
					<DetailField label="Request ID" mono wide>
						{detail.request_id}
						<CopyButton
							text={String(detail.request_id)}
							label="Request ID copied"
						/>
					</DetailField>

					<DetailField label="Timestamp" mono>
						{formatLogDateTime(detail.created_at)}
					</DetailField>

					<DetailField label="Total Time">
						<Typography
							component="span"
							sx={{
								fontFamily: theme.typography.fontFamilyCode,
								fontSize: "0.78rem",
								fontWeight: 600,
								color: timeColor(detail.total_time_ms, theme),
							}}
						>
							{formatMs(detail.total_time_ms)}
						</Typography>
					</DetailField>

					<DetailField label="Status">
						<StatusChip
							status={detail.status || (isFailed ? "failed" : "success")}
						/>
					</DetailField>

					<DetailField label="Overall Status">
						<Typography
							component="span"
							sx={{
								fontFamily: theme.typography.fontFamilyCode,
								fontSize: "0.78rem",
								fontWeight: 600,
								color:
									detail.overall_status === true
										? theme.palette.success.main
										: detail.overall_status === false
											? theme.palette.error.main
											: "text.disabled",
							}}
						>
							{detail.overall_status === true
								? "true"
								: detail.overall_status === false
									? "false"
									: "—"}
						</Typography>
					</DetailField>

					<DetailField label="Endpoint ID" mono>
						{detail.endpoint_id || "unlinked"}
					</DetailField>

					<DetailField label="Method">
						<MethodChip method={detail.method} />
					</DetailField>

					<DetailField label="Request Path" mono wide>
						{detail.path || "—"}
						{detail.path ? (
							<CopyButton text={String(detail.path)} label="Path copied" />
						) : null}
					</DetailField>
				</Box>
			</SectionAccordion>

			{}
			<SectionAccordion
				step="02"
				title="Internal Request"
				subtitle="client → gateway"
				icon={<CallReceived />}
				accent={theme.palette.info.main}
				badge={
					<CountBadge>
						{headerCount(detail.internal_request_headers)} headers
					</CountBadge>
				}
			>
				<BlockLabel>Internal Request Headers</BlockLabel>
				<KeyValueTable
					map={detail.internal_request_headers}
					nameLabel="Header Name"
					emptyText="No internal request headers were captured."
				/>

				<BlockLabel>Internal Request Body</BlockLabel>
				<JsonBlock
					value={detail.internal_request_body}
					emptyText="No internal request body was captured."
				/>

				{(detail.internal_api_client_status ||
					!isEmptyValue(detail.internal_api_client_response)) && (
					<>
						<BlockLabel
							right={
								detail.internal_api_client_status ? (
									<Chip
										size="small"
										label={detail.internal_api_client_status}
										sx={{
											height: 22,
											fontFamily: theme.typography.fontFamilyCode,
											fontSize: "0.64rem",
											"& .MuiChip-label": { px: 1 },
										}}
									/>
								) : null
							}
						>
							Client Response · gateway → caller
						</BlockLabel>
						<JsonBlock
							value={detail.internal_api_client_response}
							emptyText="No client response body was captured."
						/>
					</>
				)}
			</SectionAccordion>

			{}
			<SectionAccordion
				step="03"
				title="External Request"
				subtitle="gateway → upstream"
				icon={<NorthEast />}
				accent={theme.palette.secondary.main}
				badge={
					<CountBadge>
						{headerCount(detail.external_request_headers)} headers
					</CountBadge>
				}
			>
				<Box
					sx={{
						display: "flex",
						alignItems: "center",
						gap: 1,
						mb: 0.5,
						minWidth: 0,
					}}
				>
					<MethodChip
						method={detail.external_request_method || detail.method}
					/>
					<Tooltip title={detail.external_request_url || ""} arrow>
						<Typography
							sx={{
								fontFamily: theme.typography.fontFamilyCode,
								fontSize: "0.74rem",
								color: "text.secondary",
								wordBreak: "break-all",
								minWidth: 0,
							}}
						>
							{detail.external_request_url || "— no external URL recorded —"}
						</Typography>
					</Tooltip>
					{detail.external_request_url ? (
						<CopyButton
							text={String(detail.external_request_url)}
							label="URL copied"
						/>
					) : null}
				</Box>

				<BlockLabel>External Request Headers</BlockLabel>
				<KeyValueTable
					map={detail.external_request_headers}
					nameLabel="Header Name"
					emptyText="No external request headers were captured."
				/>

				<BlockLabel>External Query Parameters</BlockLabel>
				<KeyValueTable
					map={detail.external_query_params}
					nameLabel="Parameter"
					emptyText="No query parameters were sent upstream."
				/>

				<BlockLabel>External Request Body</BlockLabel>
				<JsonBlock
					value={detail.external_request_body}
					emptyText="No external request body was captured."
				/>
			</SectionAccordion>

			{}
			<SectionAccordion
				step="04"
				title="External Response"
				subtitle="upstream → gateway"
				icon={<SouthWest />}
				accent={theme.palette.success.main}
			>
				<Box
					sx={{
						display: "flex",
						flexWrap: "wrap",
						alignItems: "center",
						gap: 1.25,
						mb: 0.5,
					}}
				>
					<Chip
						label={detail.external_status_code ?? "—"}
						size="small"
						sx={{
							fontFamily: theme.typography.fontFamilyCode,
							fontSize: "0.7rem",
							fontWeight: 700,
							height: 24,
							color: codeColor(detail.external_status_code, theme),
							backgroundColor: alpha(
								codeColor(detail.external_status_code, theme),
								isDark ? 0.16 : 0.09,
							),
							border: `1px solid ${alpha(codeColor(detail.external_status_code, theme), 0.35)}`,
							"& .MuiChip-label": { px: 1.2 },
						}}
					/>
					<Typography
						sx={{
							fontFamily: theme.typography.fontFamilyCode,
							fontSize: "0.74rem",
							fontWeight: 600,
							color: timeColor(detail.external_response_time_ms, theme),
						}}
					>
						{formatMs(detail.external_response_time_ms)}
					</Typography>
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", fontSize: "0.52rem" }}
					>
						upstream round trip
					</Typography>
				</Box>

				<BlockLabel>External Response Body</BlockLabel>
				<JsonBlock
					value={detail.external_response}
					emptyText="No external response body was captured."
				/>
			</SectionAccordion>

			{}
			{isFailed && (
				<SectionAccordion
					step="05"
					title="Error Details"
					subtitle="failure diagnostics"
					icon={<ErrorOutline />}
					accent={theme.palette.error.main}
				>
					{errorMessage ? (
						<Alert
							severity="error"
							sx={{
								mb: 1.5,
								"& .MuiAlert-message": { wordBreak: "break-word" },
							}}
						>
							{errorMessage}
						</Alert>
					) : null}

					{!isEmptyValue(detail.full_log) ? (
						<>
							<BlockLabel
								right={
									<CopyButton
										text={String(detail.full_log)}
										label="Full log copied"
										sx={{ mr: -0.5 }}
									/>
								}
							>
								Full Log
							</BlockLabel>
							<Box
								component="pre"
								sx={{
									m: 0,
									p: 1.75,
									borderRadius: 2,
									border: "1px solid",
									borderColor: alpha(theme.palette.error.main, 0.25),
									backgroundColor: isDark
										? alpha("#050c19", 0.55)
										: alpha("#fdf6f6", 0.9),
									fontFamily: theme.typography.fontFamilyCode,
									fontSize: "0.7rem",
									lineHeight: 1.65,
									color: "text.primary",
									overflow: "auto",
									maxHeight: 280,
									whiteSpace: "pre-wrap",
									wordBreak: "break-word",
								}}
							>
								{String(detail.full_log)}
							</Box>
						</>
					) : (
						<EmptyNote text="No full log text was captured for this call." />
					)}

					{isFailed && detail.timeout_configured ? (
						<BlockLabel>
							Timeout configured · {detail.timeout_configured}s
						</BlockLabel>
					) : null}
				</SectionAccordion>
			)}
		</Box>
	);
}
