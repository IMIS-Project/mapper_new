import {
	AccountBalance,
	CallMade,
	CallReceived,
	Check,
	ContentCopy,
	ErrorOutline,
	ExpandMore,
	Token as TokenIcon,
} from "@mui/icons-material";
import {
	Accordion,
	AccordionDetails,
	AccordionSummary,
	Alert,
	Box,
	Card,
	Chip,
	IconButton,
	LinearProgress,
	Skeleton,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useMemo, useState } from "react";

import MethodChip from "../common/MethodChip";
import StatusChip from "../common/StatusChip";
import { statusLabel, statusTone } from "../common/httpStatus";
import HeadersTable from "../gateway/HeadersTable";
import { formatClock } from "../../services/localTime";
import { TOKEN_FLOW_LABELS, maskSecrets } from "./bankConstants";

/**
 * A 401 from these endpoints has two very different causes, and the response
 * body is the only way to tell them apart:
 *
 *   - "Unauthorized: Invalid or missing token" means the integration service
 *     rejected the forwarded session bearer, so the call never left IMIS.
 *   - a ResponseCode/ResponseDescription envelope means the bearer was accepted
 *     and the bank itself rejected the credentials you supplied.
 */
function explain401(result) {
	const data = result?.data;
	const body =
		typeof data === "string" ? data : JSON.stringify(data ?? {}).toLowerCase();

	if (/invalid or missing token|token has expired|not authenticated/.test(body)) {
		return "The integration service rejected the session bearer forwarded with this call, so the request never reached Bank Alfalah. Sign out and back in to refresh it; if it still fails, the integration service's SECRET_KEY does not match the auth service's.";
	}

	if (/responsecode|responsedescription|invalid credential/.test(body)) {
		return "The session bearer was accepted and the call reached Bank Alfalah, which rejected the credentials. That is the expected result for placeholder username/password.";
	}

	return "Check the response body: an 'Invalid or missing token' message means the session bearer was rejected by IMIS, while a ResponseCode envelope means Bank Alfalah rejected the credentials you entered.";
}

/**
 * The integration service normalises the bank's status code, so the HTTP
 * status and the body's own `code` field can disagree - e.g. HTTP 400
 * carrying `"code": "500"`. Say which one is authoritative rather than
 * leaving both numbers on screen unexplained.
 */
function describeStatusMismatch(result) {
	const body = result?.data;
	if (!body || typeof body !== "object" || Array.isArray(body)) return null;

	const bodyCode = body.code ?? body.ResponseCode;
	if (bodyCode == null) return null;

	const numeric = Number(bodyCode);
	if (!Number.isFinite(numeric) || numeric === result.status_code) return null;

	return `HTTP ${result.status_code} was returned by the integration service, but the body reports code ${numeric}. The service passes the transport status through and normalises the bank's own status separately, so ${numeric} is what the bank actually answered.`;
}

/** Colour-key each hop so the origin is readable at a glance. */
function layerColor(origin, theme) {
	if (origin === "mapper") return theme.palette.warning.main;
	if (origin === "bank") return theme.palette.error.main;
	return theme.palette.info.main;
}

function toPrettyJson(value) {
	if (value == null || value === "") return null;
	if (typeof value === "string") {
		try {
			return JSON.stringify(JSON.parse(value), null, 2);
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

function Panel({ icon, title, meta, defaultExpanded = false, children }) {
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

function JsonBlock({ value, emptyMessage = "Nothing captured.", maxHeight = 320 }) {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;
	const [copied, setCopied] = useState(false);
	const text = useMemo(() => toPrettyJson(value), [value]);

	const handleCopy = async () => {
		if (await copyText(text || "")) {
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
				backgroundColor: alpha(theme.palette.text.primary, 0.02),
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
				{text}
			</Box>
		</Box>
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
				backgroundColor: alpha(theme.palette.text.primary, isDark ? 0.03 : 0.015),
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
				<AccountBalance sx={{ fontSize: 25 }} />
			</Box>
			<Typography variant="subtitle1" sx={{ mb: 0.75 }}>
				No bank call captured yet
			</Typography>
			<Typography
				variant="body2"
				sx={{ color: "text.secondary", maxWidth: 400, mx: "auto" }}
			>
				Pick an operation on the left and send it. The full request sent to
				the integration service and its response appear here.
			</Typography>
		</Box>
	);
}

export default function BankCallViewer({ result, operation, timestamp, loading }) {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;
	const isDark = theme.palette.mode === "dark";
	const { palette } = theme;

	const failed = Boolean(result) && result.success === false;
	const code = result?.status_code ?? null;
	const tone = statusTone(code, palette);

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
			<Box>
				<Panel icon={<AccountBalance />} title="Overview" defaultExpanded>
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

				<Panel icon={<TokenIcon />} title="Token flow">
					<Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.25 }}>
						<Box
							sx={{
								flex: "1 1 240px",
								px: 1.5,
								py: 1.2,
								borderRadius: 2,
								border: "1px solid",
								borderColor: "divider",
							}}
						>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.5rem", mb: 0.5 }}
							>
								Flow used
							</Typography>
							<Typography variant="body2" sx={{ fontWeight: 600 }}>
								{TOKEN_FLOW_LABELS[result.token_flow] || result.token_flow || "—"}
							</Typography>
						</Box>
						<Box
							sx={{
								flex: "1 1 240px",
								px: 1.5,
								py: 1.2,
								borderRadius: 2,
								border: "1px solid",
								borderColor: "divider",
							}}
						>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.5rem", mb: 0.5 }}
							>
								Token source
							</Typography>
							<Typography variant="body2" sx={{ fontWeight: 600 }}>
								{result.token_source || "—"}
							</Typography>
						</Box>
						<Box
							sx={{
								flex: "1 1 240px",
								px: 1.5,
								py: 1.2,
								borderRadius: 2,
								border: "1px solid",
								borderColor: "divider",
							}}
						>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.5rem", mb: 0.5 }}
							>
								Correlation ID
							</Typography>
							<Typography
								sx={{ fontFamily: codeFont, fontSize: "0.78rem", wordBreak: "break-all" }}
							>
								{result.correlation_id || "—"}
							</Typography>
						</Box>
					</Box>
					{operation?.downstream ? (
						<Typography
							variant="caption"
							sx={{ display: "block", mt: 1.5, color: "text.disabled" }}
						>
							Downstream target: {operation.downstream}
						</Typography>
					) : null}
				</Panel>

				<Panel icon={<CallMade />} title="Request to integration service">
					<Box sx={{ display: "flex", alignItems: "center", gap: 1.25, mb: 1.5, flexWrap: "wrap" }}>
						{result.targetMethod ? <MethodChip method={result.targetMethod} /> : null}
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
							{result.targetUrl || "—"}
						</Typography>
					</Box>

					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", mb: 0.75 }}
					>
						Headers (secrets masked)
					</Typography>
					<HeadersTable
						headers={result.request_headers}
						emptyMessage="No headers were recorded."
					/>

					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", mt: 1.75, mb: 0.75 }}
					>
						Body
					</Typography>
					{result.request_body ? (
						<Typography
							variant="caption"
							sx={{ display: "block", color: "text.disabled", mb: 0.75 }}
						>
							Credentials are redacted here; the values sent to the
							integration service were not modified.
						</Typography>
					) : null}
					<JsonBlock
						value={result.request_body}
						emptyMessage="No request body was sent."
					/>
				</Panel>

				<Panel icon={<CallReceived />} title="Response">
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", mb: 0.75 }}
					>
						Response headers
					</Typography>
					<HeadersTable
						headers={result.response_headers}
						emptyMessage="No response headers were captured."
					/>

					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", mt: 1.75, mb: 0.75 }}
					>
						Response body
					</Typography>
					{result.data ? (
						<Typography
							variant="caption"
							sx={{ display: "block", color: "text.disabled", mb: 0.75 }}
						>
							Access tokens are redacted on screen. A token captured here is
							chained into the next request automatically.
						</Typography>
					) : null}
					<JsonBlock
						value={maskSecrets(result.data)}
						emptyMessage="The service returned an empty body."
						maxHeight={420}
					/>
				</Panel>

				{failed ? (
					<Panel
						icon={<ErrorOutline />}
						title="Error"
						defaultExpanded
						meta={code != null ? `HTTP ${code}` : undefined}
					>
						<Box
							sx={{
								display: "flex",
								alignItems: "center",
								gap: 1,
								flexWrap: "wrap",
								mb: 1.25,
							}}
						>
							<Chip
								size="small"
								label={
									result.error_source === "mapper"
										? "Raised by this console"
										: "Returned by the integration service"
								}
								sx={{
									height: 22,
									fontSize: "0.64rem",
									fontWeight: 600,
									color:
										result.error_source === "mapper"
											? theme.palette.warning.main
											: theme.palette.error.main,
									backgroundColor: alpha(
										result.error_source === "mapper"
											? theme.palette.warning.main
											: theme.palette.error.main,
										0.12,
									),
								}}
							/>
						</Box>

						{result.error_layers?.length ? (
							<Box
								sx={{
									display: "flex",
									flexDirection: "column",
									gap: 1,
								}}
							>
								{result.error_layers.map((layer, index) => (
									<Box
										key={`${layer.origin}-${index}`}
										sx={{
											px: 1.75,
											py: 1.35,
											borderRadius: 2,
											border: "1px solid",
											borderColor: "divider",
											borderLeftWidth: 3,
											borderLeftColor: layerColor(layer.origin, theme),
											backgroundColor: alpha(
												layerColor(layer.origin, theme),
												theme.palette.mode === "dark" ? 0.08 : 0.04,
											),
										}}
									>
										<Box
											sx={{
												display: "flex",
												alignItems: "center",
												gap: 1,
												flexWrap: "wrap",
												mb: 0.5,
											}}
										>
											<Typography
												sx={{
													fontSize: "0.72rem",
													fontWeight: 600,
													color: layerColor(layer.origin, theme),
												}}
											>
												{layer.label}
											</Typography>
											{layer.status_code != null ? (
												<Chip
													size="small"
													label={statusLabel(layer.status_code)}
													sx={{
														height: 19,
														fontSize: "0.6rem",
														fontWeight: 600,
														fontFamily: codeFont,
														color: "text.secondary",
														backgroundColor: alpha(
															theme.palette.text.primary,
															0.07,
														),
													}}
												/>
											) : null}
										</Box>
										<Typography
											sx={{
												fontFamily: codeFont,
												fontSize: "0.76rem",
												lineHeight: 1.6,
												wordBreak: "break-word",
												whiteSpace: "pre-wrap",
											}}
										>
											{layer.message}
										</Typography>
									</Box>
								))}
							</Box>
						) : (
							<Alert
								severity="error"
								variant="outlined"
								icon={false}
								sx={{
									"& .MuiAlert-message": {
										fontFamily: codeFont,
										fontSize: "0.76rem",
										wordBreak: "break-word",
										whiteSpace: "pre-wrap",
									},
								}}
							>
								{result.error || "The call failed without an error message."}
							</Alert>
						)}
						{describeStatusMismatch(result) ? (
							<Alert
								severity="warning"
								variant="outlined"
								sx={{
									mt: 1.5,
									"& .MuiAlert-message": { fontSize: "0.76rem" },
								}}
							>
								{describeStatusMismatch(result)}
							</Alert>
						) : null}
						{code === 401 ? (
							<Alert
								severity="info"
								variant="outlined"
								sx={{
									mt: 1.5,
									"& .MuiAlert-message": { fontSize: "0.76rem" },
								}}
							>
								{explain401(result)}
							</Alert>
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
						Bank response inspector
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