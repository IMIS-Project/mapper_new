import {
	ArrowForward,
	CheckCircleOutlined,
	Close,
	ContentCopy,
	DataObjectOutlined,
	Done,
	KeyOutlined,
} from "@mui/icons-material";
import {
	Box,
	Button,
	Chip,
	CircularProgress,
	Dialog,
	DialogActions,
	DialogContent,
	DialogTitle,
	Divider,
	IconButton,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableRow,
	ToggleButton,
	ToggleButtonGroup,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, lighten, useTheme } from "@mui/material/styles";
import { useMemo, useState } from "react";

import MethodChip from "../common/MethodChip";
import { PARAM_TYPE_COLORS, PARAM_TYPE_OPTIONS } from "./mappingModel";

const HEAD_CELL_SX = {
	fontFamily: "var(--font-mono)",
	fontSize: "0.6rem",
	fontWeight: 600,
	letterSpacing: "0.14em",
	textTransform: "uppercase",
	color: "text.secondary",
	py: 0.75,
};

function TypeChip({ type }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const base = PARAM_TYPE_COLORS[type] || "#546e7a";

	const textColor = isDark ? lighten(base, 0.35) : base;

	return (
		<Chip
			size="small"
			label={type}
			sx={{
				height: 22,
				fontFamily: "var(--font-mono)",
				fontSize: "0.64rem",
				fontWeight: 700,
				color: textColor,
				backgroundColor: alpha(base, isDark ? 0.18 : 0.1),
				border: `1px solid ${alpha(base, isDark ? 0.45 : 0.3)}`,
				"& .MuiChip-label": { px: 0.9 },
			}}
		/>
	);
}

export default function MappingPreview({
	open,
	onClose,
	onConfirm,
	saving = false,
	payload,
	isEdit = false,
}) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const codeFont = theme.typography.fontFamilyCode;

	const [mode, setMode] = useState("formatted");
	const [copied, setCopied] = useState(false);

	const handleClose = () => {
		setMode("formatted");
		setCopied(false);
		onClose?.();
	};

	const jsonText = useMemo(() => {
		try {
			return JSON.stringify(payload ?? {}, null, 2);
		} catch {
			return String(payload);
		}
	}, [payload]);

	const mappings = Array.isArray(payload?.mappings) ? payload.mappings : [];
	const enabledCount = mappings.filter((row) => row.enabled).length;
	const hasAuth = Boolean(
		payload?.api_id || payload?.api_password || payload?.api_auth_url,
	);

	const handleCopy = async () => {
		try {
			await navigator.clipboard.writeText(jsonText);
			setCopied(true);
			window.setTimeout(() => setCopied(false), 1800);
		} catch {
			setCopied(false);
		}
	};

	const routePanelSx = {
		border: "1px solid",
		borderColor: "divider",
		borderRadius: 2,
		px: 2,
		py: 1.75,
		backgroundColor: alpha(
			theme.palette.background.default,
			isDark ? 0.5 : 0.65,
		),
	};

	return (
		<Dialog
			open={open}
			onClose={saving ? undefined : handleClose}
			maxWidth="md"
			fullWidth
		>
			<DialogTitle
				sx={{
					position: "relative",
					pr: 6,
					"&::before": {
						content: '""',
						position: "absolute",
						top: 0,
						left: 0,
						right: 0,
						height: 3,
						background: "linear-gradient(90deg, #1e8d39 0%, #4ecb6d 100%)",
					},
				}}
			>
				<Typography
					className="mono-label"
					component="span"
					sx={{ display: "block", color: "text.disabled", fontSize: "0.55rem" }}
				>
					{isEdit ? "Preview — request changes" : "Preview — request shape"}
				</Typography>
				<Typography
					component="span"
					variant="h6"
					sx={{ display: "block", lineHeight: 1.3 }}
				>
					{isEdit ? "Review updated mapping" : "Review mapping before saving"}
				</Typography>

				<Tooltip title="Close preview" arrow>
					<IconButton
						onClick={handleClose}
						disabled={saving}
						aria-label="Close preview"
						sx={{
							position: "absolute",
							right: 12,
							top: 14,
							color: "text.secondary",
						}}
					>
						<Close fontSize="small" />
					</IconButton>
				</Tooltip>
			</DialogTitle>

			<DialogContent dividers sx={{ px: { xs: 2, sm: 3 }, py: 2.5 }}>
				<ToggleButtonGroup
					size="small"
					exclusive
					value={mode}
					onChange={(_event, next) => next && setMode(next)}
					sx={{ mb: 2.5 }}
				>
					<ToggleButton
						value="formatted"
						sx={{ px: 1.75, fontSize: "0.74rem", textTransform: "none" }}
					>
						Formatted
					</ToggleButton>
					<ToggleButton
						value="json"
						sx={{ px: 1.75, fontSize: "0.74rem", textTransform: "none" }}
					>
						<DataObjectOutlined sx={{ fontSize: 15, mr: 0.75 }} />
						Raw JSON
					</ToggleButton>
				</ToggleButtonGroup>

				{mode === "formatted" ? (
					<Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
						{}
						<Box
							sx={{
								...routePanelSx,
								display: "grid",
								gridTemplateColumns: { xs: "1fr", sm: "1fr auto 1fr" },
								gap: 2,
								alignItems: "center",
							}}
						>
							<Box sx={{ minWidth: 0 }}>
								<Typography
									className="mono-label"
									sx={{ color: "text.disabled", fontSize: "0.55rem", mb: 0.75 }}
								>
									Internal
								</Typography>
								<Box
									sx={{
										display: "flex",
										alignItems: "center",
										gap: 1,
										mb: 0.75,
									}}
								>
									<MethodChip method={payload?.sourceMethod} />
								</Box>
								<Typography
									sx={{
										fontFamily: codeFont,
										fontSize: "0.78rem",
										wordBreak: "break-all",
									}}
								>
									{payload?.targetUrl || "—"}
								</Typography>
							</Box>

							<ArrowForward
								sx={{
									color: "text.disabled",
									fontSize: 20,
									justifySelf: "center",
									transform: { xs: "rotate(90deg)", sm: "none" },
								}}
							/>

							<Box sx={{ minWidth: 0 }}>
								<Typography
									className="mono-label"
									sx={{ color: "text.disabled", fontSize: "0.55rem", mb: 0.75 }}
								>
									External
								</Typography>
								<Box
									sx={{
										display: "flex",
										alignItems: "center",
										gap: 1,
										mb: 0.75,
									}}
								>
									<MethodChip method={payload?.targetMethod} />
								</Box>
								<Typography
									sx={{
										fontFamily: codeFont,
										fontSize: "0.78rem",
										wordBreak: "break-all",
									}}
								>
									{payload?.sourceUrl || "—"}
								</Typography>
							</Box>
						</Box>

						{}
						<Box
							sx={{
								display: "flex",
								gap: 1,
								flexWrap: "wrap",
								alignItems: "center",
							}}
						>
							<Chip
								size="small"
								icon={<CheckCircleOutlined sx={{ fontSize: 15 }} />}
								label={`${enabledCount} of ${mappings.length} enabled`}
								sx={{
									fontFamily: codeFont,
									fontSize: "0.68rem",
									color: theme.palette.success.main,
									backgroundColor: alpha(
										theme.palette.success.main,
										isDark ? 0.14 : 0.08,
									),
									border: `1px solid ${alpha(theme.palette.success.main, 0.3)}`,
								}}
							/>
							{PARAM_TYPE_OPTIONS.filter((type) =>
								mappings.some((row) => row.parameterType === type),
							).map((type) => (
								<TypeChip key={type} type={type} />
							))}
							<Chip
								size="small"
								icon={<KeyOutlined sx={{ fontSize: 14 }} />}
								label={hasAuth ? "Upstream auth enabled" : "No upstream auth"}
								variant="outlined"
								sx={{
									fontFamily: codeFont,
									fontSize: "0.68rem",
									color: hasAuth ? "text.primary" : "text.disabled",
								}}
							/>
						</Box>

						{}
						{hasAuth && (
							<>
								<Divider>
									<Typography
										className="mono-label"
										sx={{ color: "text.disabled", fontSize: "0.55rem" }}
									>
										Authentication
									</Typography>
								</Divider>
								<Box
									sx={{
										...routePanelSx,
										display: "grid",
										gridTemplateColumns: { xs: "1fr", sm: "repeat(3, 1fr)" },
										gap: 2,
									}}
								>
									{[
										["API ID", payload?.api_id || "—"],
										[
											"API password",
											payload?.api_password ? "•".repeat(10) : "—",
										],
										["Auth URL", payload?.api_auth_url || "—"],
									].map(([label, value]) => (
										<Box key={label} sx={{ minWidth: 0 }}>
											<Typography
												className="mono-label"
												sx={{
													color: "text.disabled",
													fontSize: "0.53rem",
													mb: 0.5,
												}}
											>
												{label}
											</Typography>
											<Typography
												sx={{
													fontFamily: codeFont,
													fontSize: "0.76rem",
													wordBreak: "break-all",
												}}
											>
												{value}
											</Typography>
										</Box>
									))}
								</Box>
							</>
						)}

						{}
						<Box>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.55rem", mb: 1 }}
							>
								Parameter mappings
							</Typography>
							<TableContainer
								sx={{
									border: "1px solid",
									borderColor: "divider",
									borderRadius: 2,
									maxHeight: 300,
								}}
							>
								<Table size="small" stickyHeader sx={{ minWidth: 480 }}>
									<TableHead>
										<TableRow
											sx={{
												"& th": {
													backgroundColor: isDark
														? alpha(theme.palette.background.default, 0.94)
														: alpha(theme.palette.background.default, 0.92),
												},
											}}
										>
											<TableCell sx={{ ...HEAD_CELL_SX, width: 44 }}>
												#
											</TableCell>
											<TableCell sx={HEAD_CELL_SX}>External field</TableCell>
											<TableCell sx={{ ...HEAD_CELL_SX, width: 30 }} />
											<TableCell sx={HEAD_CELL_SX}>Internal field</TableCell>
											<TableCell sx={{ ...HEAD_CELL_SX, width: 96 }}>
												Type
											</TableCell>
											<TableCell
												align="right"
												sx={{ ...HEAD_CELL_SX, width: 90 }}
											>
												State
											</TableCell>
										</TableRow>
									</TableHead>
									<TableBody>
										{mappings.length === 0 ? (
											<TableRow>
												<TableCell
													colSpan={6}
													align="center"
													sx={{ py: 3, color: "text.disabled" }}
												>
													<Typography variant="body2">
														No parameter mappings.
													</Typography>
												</TableCell>
											</TableRow>
										) : (
											mappings.map((row, index) => (
												<TableRow
													key={`${row.sourceField}-${row.targetField}-${index}`}
													hover
												>
													<TableCell
														sx={{
															fontFamily: codeFont,
															fontSize: "0.68rem",
															color: "text.disabled",
														}}
													>
														{String(index + 1).padStart(2, "0")}
													</TableCell>
													<TableCell>
														<Typography
															sx={{
																fontFamily: codeFont,
																fontSize: "0.76rem",
																color: row.enabled
																	? "text.primary"
																	: "text.disabled",
															}}
														>
															{row.sourceField || "—"}
														</Typography>
													</TableCell>
													<TableCell sx={{ px: 0 }}>
														<ArrowForward
															sx={{ fontSize: 14, color: "text.disabled" }}
														/>
													</TableCell>
													<TableCell>
														<Typography
															sx={{
																fontFamily: codeFont,
																fontSize: "0.76rem",
																color: row.enabled
																	? "text.primary"
																	: "text.disabled",
															}}
														>
															{row.targetField || "—"}
														</Typography>
													</TableCell>
													<TableCell>
														<TypeChip type={row.parameterType} />
													</TableCell>
													<TableCell align="right">
														<Typography
															variant="caption"
															sx={{
																fontWeight: 600,
																color: row.enabled
																	? theme.palette.success.main
																	: "text.disabled",
															}}
														>
															{row.enabled ? "Enabled" : "Disabled"}
														</Typography>
													</TableCell>
												</TableRow>
											))
										)}
									</TableBody>
								</Table>
							</TableContainer>
						</Box>
					</Box>
				) : (
					<Box sx={{ position: "relative" }}>
						<Tooltip title={copied ? "Copied" : "Copy JSON"} arrow>
							<Button
								size="small"
								onClick={handleCopy}
								startIcon={
									copied ? (
										<Done sx={{ fontSize: 15 }} />
									) : (
										<ContentCopy sx={{ fontSize: 15 }} />
									)
								}
								sx={{
									position: "absolute",
									top: -8,
									right: 0,
									zIndex: 1,
									fontSize: "0.7rem",
									color: "text.secondary",
								}}
							>
								{copied ? "Copied" : "Copy"}
							</Button>
						</Tooltip>
						<Box
							component="pre"
							sx={{
								m: 0,
								p: 2,
								pt: 3.5,
								border: "1px solid",
								borderColor: "divider",
								borderRadius: 2,
								backgroundColor: alpha(
									theme.palette.background.default,
									isDark ? 0.6 : 0.7,
								),
								fontFamily: codeFont,
								fontSize: "0.74rem",
								lineHeight: 1.65,
								maxHeight: 420,
								overflow: "auto",
								whiteSpace: "pre-wrap",
								wordBreak: "break-word",
							}}
						>
							{jsonText}
						</Box>
					</Box>
				)}
			</DialogContent>

			<DialogActions sx={{ px: { xs: 2, sm: 3 }, py: 2 }}>
				<Button onClick={handleClose} disabled={saving} color="inherit">
					Cancel
				</Button>
				<Button
					variant="contained"
					onClick={onConfirm}
					disabled={saving}
					startIcon={
						saving ? (
							<CircularProgress size={16} thickness={5} color="inherit" />
						) : null
					}
				>
					{saving ? "Saving…" : isEdit ? "Save changes" : "Save mapping"}
				</Button>
			</DialogActions>
		</Dialog>
	);
}
