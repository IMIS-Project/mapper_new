import {
	ClearAll,
	PlayArrow,
	Refresh as RefreshIcon,
	WarningAmber,
} from "@mui/icons-material";
import {
	Alert,
	Box,
	Button,
	Card,
	CircularProgress,
	Divider,
	FormControl,
	InputLabel,
	MenuItem,
	Select,
	TextField,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useMemo, useState } from "react";

import MethodChip from "../common/MethodChip";

const GROUPS = [
	{ id: "token", label: "Tokens" },
	{ id: "account-opening", label: "Account opening" },
	{ id: "c2c", label: "C2C" },
];

function buildInitialValues(operation) {
	const values = {};
	(operation?.fields ?? []).forEach((field) => {
		values[field.name] = field.default ?? "";
	});
	return values;
}

function SectionLabel({ children }) {
	return (
		<Typography
			className="mono-label"
			sx={{ color: "text.disabled", fontSize: "0.55rem", mb: 1.25, mt: 0.5 }}
		>
			{children}
		</Typography>
	);
}

function TokenBanner({ token, operation, onRunToken, chainingStep }) {
	const theme = useTheme();

	if (!operation?.tokenHeader) return null;

	const captured = token?.value;
	const autoChained = Boolean(operation.autoChain);

	return (
		<Alert
			severity={captured ? "success" : autoChained ? "info" : "warning"}
			variant="outlined"
			icon={
				captured ? (
					<RefreshIcon fontSize="inherit" />
				) : (
					<WarningAmber fontSize="inherit" />
				)
			}
			sx={{
				mb: 2,
				alignItems: "center",
				"& .MuiAlert-message": { width: "100%" },
			}}
		>
			<Typography
				variant="body2"
				sx={{ fontWeight: 600, color: theme.palette.text.primary }}
			>
				{autoChained ? "Bank Auth runs automatically" : "Chained Bank Auth token"}
			</Typography>
			<Typography
				variant="caption"
				sx={{ display: "block", color: "text.secondary", mt: 0.35 }}
			>
				This endpoint reads the token from the{" "}
				<Box
					component="code"
					sx={{
						fontFamily: theme.typography.fontFamilyCode,
						fontSize: "0.72rem",
						px: 0.5,
						borderRadius: 1,
						backgroundColor: alpha(theme.palette.text.primary, 0.07),
					}}
				>
					{operation.tokenHeader}
				</Box>{" "}
				header and does not authenticate itself.
			</Typography>

			{chainingStep ? (
				<Typography
					variant="caption"
					sx={{
						display: "flex",
						alignItems: "center",
						gap: 0.75,
						color: "text.secondary",
						mt: 0.75,
					}}
				>
					<CircularProgress size={11} thickness={5} />
					Running {chainingStep}…
				</Typography>
			) : null}

			{captured ? (
				<Typography
					variant="caption"
					sx={{
						display: "block",
						color: "text.secondary",
						mt: 0.75,
						fontFamily: theme.typography.fontFamilyCode,
					}}
				>
					Last token captured at {token.capturedLabel}.
				</Typography>
			) : autoChained ? (
				<Typography
					variant="caption"
					sx={{ display: "block", color: "text.secondary", mt: 0.75 }}
				>
					Sending the request will call {operation.autoChainOperation} with the
					username and password from this form first.
				</Typography>
			) : (
				<Button
					size="small"
					variant="outlined"
					onClick={onRunToken}
					startIcon={<PlayArrow fontSize="inherit" />}
					sx={{ mt: 1.25, fontSize: "0.72rem" }}
				>
					Run Bank Auth to capture a token
				</Button>
			)}
		</Alert>
	);
}

export default function BankOperationForm({
	operations,
	operation,
	selectedGroup,
	onGroupChange,
	onSelectOperation,
	token,
	onRunToken,
	onSubmit,
	loading,
	chainingStep,
	chainError,
}) {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;

	const [values, setValues] = useState(() => buildInitialValues(operation));
	const [errors, setErrors] = useState({});
	const [correlationId, setCorrelationId] = useState("");

	const grouped = useMemo(() => {
		const map = {};
		GROUPS.forEach((group) => {
			map[group.id] = operations.filter((op) => op.group === group.id);
		});
		return map;
	}, [operations]);

	const visibleOperations = grouped[selectedGroup] ?? [];

	const handleChange = (name, value) => {
		setValues((prev) => ({ ...prev, [name]: value }));
		setErrors((prev) => {
			if (!prev[name]) return prev;
			const next = { ...prev };
			delete next[name];
			return next;
		});
	};

	const handleSubmit = () => {
		const nextErrors = {};
		const payload = {};

		(operation?.fields ?? []).forEach((field) => {
			const raw = values[field.name];
			const text = raw == null ? "" : String(raw).trim();
			if (field.required && !text) {
				nextErrors[field.name] = `${field.label} is required.`;
			}

			// Mirror the upstream digit rules. The service validates these with
			// a pydantic validator whose error path returns 500, so catching it
			// here keeps a typo from becoming a server error.
			if (!nextErrors[field.name] && field.digits && text) {
				const digits = text.replace(/\D/g, "");
				if (!digits) {
					nextErrors[field.name] = `${field.label} must contain digits.`;
				} else if (digits.length !== field.digits) {
					nextErrors[field.name] = `${field.label} must be exactly ${field.digits} digits.`;
				}
			}

			if (text) payload[field.name] = text;
		});

		if (Object.keys(nextErrors).length > 0) {
			setErrors(nextErrors);
			return;
		}

		onSubmit({ payload, correlationId: correlationId.trim() });
	};

	return (
		<Card
			elevation={0}
			sx={{
				borderRadius: 3,
				border: "1px solid",
				borderColor: "divider",
				overflow: "hidden",
			}}
		>
			<Box sx={{ px: 2.25, py: 1.75, borderBottom: "1px solid", borderColor: "divider" }}>
				<Typography
					className="mono-label"
					sx={{ color: "text.disabled", fontSize: "0.55rem" }}
				>
					Bank operation
				</Typography>
				<Typography variant="subtitle1">Compose a request</Typography>
			</Box>

			<Box sx={{ p: 2.25 }}>
				<Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
					{GROUPS.map((group) => {
						const active = selectedGroup === group.id;
						const count = (grouped[group.id] ?? []).length;
						return (
							<Button
								key={group.id}
								size="small"
								variant={active ? "contained" : "outlined"}
								onClick={() => onGroupChange(group.id)}
								sx={{
									fontSize: "0.74rem",
									px: 1.5,
									py: 0.4,
									minWidth: 0,
									borderRadius: "8px",
								}}
							>
								{group.label}
								<Typography
									component="span"
									sx={{
										ml: 0.75,
										fontFamily: codeFont,
										fontSize: "0.66rem",
										opacity: 0.7,
									}}
								>
									{count}
								</Typography>
							</Button>
						);
					})}
				</Box>

				<Divider sx={{ my: 2 }} />

				<Box sx={{ display: "flex", flexDirection: "column", gap: 0.75 }}>
					{visibleOperations.map((op) => {
						const active = op.id === operation?.id;
						return (
							<Box
								key={op.id}
								role="button"
								tabIndex={0}
								onClick={() => onSelectOperation(op)}
								onKeyDown={(event) => {
									if (event.key === "Enter" || event.key === " ") {
										event.preventDefault();
										onSelectOperation(op);
									}
								}}
								sx={{
									display: "flex",
									alignItems: "flex-start",
									gap: 1.25,
									px: 1.5,
									py: 1.1,
									cursor: "pointer",
									borderRadius: 2,
									border: "1px solid",
									borderColor: active ? "primary.main" : "divider",
									backgroundColor: active
										? alpha(theme.palette.primary.main, 0.08)
										: "transparent",
									transition: "background-color 0.15s ease",
									"&:hover": {
										backgroundColor: active
											? alpha(theme.palette.primary.main, 0.12)
											: alpha(theme.palette.primary.main, 0.04),
									},
								}}
							>
								<Box sx={{ pt: 0.25, flexShrink: 0 }}>
									<MethodChip method={op.method} size="small" />
								</Box>
								<Box sx={{ minWidth: 0, flex: 1 }}>
									<Typography
										variant="body2"
										sx={{ fontWeight: active ? 600 : 500 }}
									>
										{op.label}
									</Typography>
									<Typography
										variant="caption"
										sx={{
											display: "block",
											color: "text.secondary",
											lineHeight: 1.5,
											mt: 0.25,
										}}
									>
										{op.summary}
									</Typography>
									<Typography
										className="mono-label"
										sx={{
											display: "block",
											color: "text.disabled",
											fontSize: "0.58rem",
											mt: 0.5,
											wordBreak: "break-all",
										}}
									>
										{op.path}
									</Typography>
								</Box>
							</Box>
						);
					})}
				</Box>

				{operation ? (
					<>
						<Divider sx={{ my: 2 }} />

						<Typography
							variant="subtitle2"
							sx={{ fontWeight: 600, mb: 0.5 }}
						>
							{operation.label}
						</Typography>

						<TokenBanner
							token={token}
							operation={operation}
							onRunToken={onRunToken}
							chainingStep={chainingStep}
						/>

						{chainError ? (
							<Alert severity="error" variant="outlined" sx={{ mb: 2 }}>
								{chainError}
							</Alert>
						) : null}

						{operation.method === "GET" ? (
							<Alert
								severity="info"
								variant="outlined"
								sx={{ mb: 2, "& .MuiAlert-message": { fontSize: "0.76rem" } }}
							>
								Read-only lookup. It answers from the IMIS database and
								never reaches Bank Alfalah, so no bank token is involved.
							</Alert>
						) : null}

						{operation.method === "GET" ? null : (
							<>
								<SectionLabel>Correlation ID</SectionLabel>
								<TextField
									fullWidth
									size="small"
									value={correlationId}
									onChange={(event) => setCorrelationId(event.target.value)}
									placeholder="auto-generated if left blank"
									helperText={
										operation.requiresCorrelationId
											? "This endpoint requires the x-correlation-id header."
											: "Optional; the integration service generates one when omitted."
									}
									sx={{
										mb: 2,
										"& input": { fontFamily: codeFont, fontSize: "0.78rem" },
										"& .MuiFormHelperText-root": { fontSize: "0.66rem" },
									}}
								/>
							</>
						)}

						<SectionLabel>Payload</SectionLabel>
						<Box
							sx={{
								display: "grid",
								gridTemplateColumns: {
									xs: "minmax(0, 1fr)",
									sm: "repeat(auto-fit, minmax(240px, 1fr))",
								},
								gap: 1.75,
							}}
						>
							{(operation.fields ?? []).map((field) => {
								const fullWidth = field.kind !== "select";
								return (
									<Box
										key={field.name}
										sx={{ gridColumn: fullWidth ? "1 / -1" : "auto" }}
									>
										{field.kind === "select" ? (
											<FormControl fullWidth size="small" error={Boolean(errors[field.name])}>
												<InputLabel id={`${field.name}-label`}>
													{field.label}
												</InputLabel>
												<Select
													labelId={`${field.name}-label`}
													label={field.label}
													value={values[field.name] ?? ""}
													onChange={(event) =>
														handleChange(field.name, event.target.value)
													}
													sx={{ fontFamily: codeFont, fontSize: "0.78rem" }}
												>
													{field.options.map((option) => (
														<MenuItem key={option} value={option}>
															{option}
														</MenuItem>
													))}
												</Select>
											</FormControl>
										) : (
											<TextField
												fullWidth
												size="small"
												type={field.kind === "password" ? "password" : "text"}
												label={field.label}
												value={values[field.name] ?? ""}
												onChange={(event) =>
													handleChange(field.name, event.target.value)
												}
												placeholder={field.placeholder}
												error={Boolean(errors[field.name])}
												helperText={errors[field.name] || field.help || " "}
												slotProps={{
													htmlInput: { "data-field": field.name },
												}}
												sx={{
													"& input": { fontFamily: codeFont, fontSize: "0.78rem" },
													"& .MuiFormHelperText-root": {
														fontSize: "0.66rem",
														minHeight: "1em",
													},
												}}
											/>
										)}
									</Box>
								);
							})}
						</Box>

						<Box
							sx={{
								display: "flex",
								alignItems: "center",
								gap: 1.25,
								mt: 2.5,
							}}
						>
							<Button
								variant="contained"
								onClick={handleSubmit}
								disabled={loading}
								startIcon={
									loading ? (
										<CircularProgress size={15} color="inherit" />
									) : (
										<PlayArrow fontSize="small" />
									)
								}
								sx={{ px: 2.5 }}
							>
								Send request
							</Button>
							<Tooltip title="Clear the form">
								<Button
									size="small"
									color="inherit"
									onClick={() => {
										setValues(buildInitialValues(operation));
										setErrors({});
										setCorrelationId("");
									}}
									startIcon={<ClearAll fontSize="small" />}
									sx={{ color: "text.secondary" }}
								>
									Reset
								</Button>
							</Tooltip>
						</Box>
					</>
				) : null}
			</Box>
		</Card>
	);
}