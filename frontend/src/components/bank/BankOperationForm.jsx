import {
	ClearAll,
	DataObject as DataObjectIcon,
	PlayArrow,
	Refresh as RefreshIcon,
	Tune as TuneIcon,
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
	ToggleButton,
	ToggleButtonGroup,
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

const INPUT_MODES = [
	{ id: "form", label: "Input boxes", icon: <TuneIcon fontSize="small" /> },
	{ id: "json", label: "JSON", icon: <DataObjectIcon fontSize="small" /> },
];

function buildInitialValues(operation) {
	const values = {};
	(operation?.fields ?? []).forEach((field) => {
		values[field.name] = field.default ?? "";
	});
	return values;
}

/** Values -> payload, dropping blanks so optional fields stay optional. */
function valuesToPayload(operation, values) {
	const payload = {};
	const known = new Set();

	(operation?.fields ?? []).forEach((field) => {
		known.add(field.name);
		const raw = values[field.name];
		const text = raw == null ? "" : String(raw).trim();
		if (text) payload[field.name] = text;
	});

	// Keys added in the JSON editor that the form has no input for. They must
	// survive a round trip rather than being silently dropped.
	Object.entries(values).forEach(([key, raw]) => {
		const text = raw == null ? "" : String(raw).trim();
		if (!known.has(key) && text) payload[key] = text;
	});

	return payload;
}

function payloadToValues(operation, payload) {
	const values = buildInitialValues(operation);
	Object.entries(payload).forEach(([key, value]) => {
		values[key] =
			value == null
				? ""
				: typeof value === "object"
					? JSON.stringify(value)
					: String(value);
	});
	return values;
}

/** Renders a field's type the way an API reference does. */
function TypeBadge({ field, codeFont }) {
	const label = field.enum ? "enum" : field.format || field.type || "string";
	return (
		<Typography
			component="span"
			sx={{
				fontFamily: codeFont,
				fontSize: "0.72rem",
				color: "text.secondary",
			}}
		>
			{label}
		</Typography>
	);
}

/**
 * Swagger-style request body reference: every field with its type, whether it
 * is required, and its constraints. Sits above the JSON editor so the shape of
 * the payload is documented in the same terms as the API reference.
 */
function SchemaTable({ operation, codeFont }) {
	const fields = operation?.fields ?? [];
	if (fields.length === 0) return null;

	return (
		<Box
			sx={{
				mb: 1.5,
				borderRadius: 2,
				border: "1px solid",
				borderColor: "divider",
				overflow: "hidden",
			}}
		>
			<Box
				sx={{
					px: 1.75,
					py: 1,
					backgroundColor: alpha("#1976d2", 0.08),
					borderBottom: "1px solid",
					borderColor: "divider",
				}}
			>
				<Typography
					className="mono-label"
					sx={{ fontSize: "0.55rem", color: "text.secondary" }}
				>
					Schema · application/json
				</Typography>
			</Box>

			<Box component="table" sx={{ width: "100%", borderCollapse: "collapse" }}>
				<Box component="thead">
					<Box component="tr">
						{["Field", "Type", "Required", "Notes"].map((head) => (
							<Box
								key={head}
								component="th"
								sx={{
									px: 1.75,
									py: 0.75,
									textAlign: "left",
									fontFamily: codeFont,
									fontSize: "0.58rem",
									fontWeight: 500,
									letterSpacing: "0.12em",
									textTransform: "uppercase",
									color: "text.disabled",
									borderBottom: "1px solid",
									borderColor: "divider",
									whiteSpace: "nowrap",
								}}
							>
								{head}
							</Box>
						))}
					</Box>
				</Box>

				<Box component="tbody">
					{fields.map((field) => (
						<Box
							key={field.name}
							component="tr"
							sx={{
								"&:hover": { backgroundColor: alpha("#1976d2", 0.04) },
							}}
						>
							<Box
								component="td"
								sx={{
									px: 1.75,
									py: 0.9,
									fontFamily: codeFont,
									fontSize: "0.76rem",
									fontWeight: 600,
									whiteSpace: "nowrap",
									borderBottom: "1px solid",
									borderColor: "divider",
								}}
							>
								{field.name}
							</Box>

							<Box
								component="td"
								sx={{
									px: 1.75,
									py: 0.9,
									whiteSpace: "nowrap",
									borderBottom: "1px solid",
									borderColor: "divider",
								}}
							>
								<TypeBadge field={field} codeFont={codeFont} />
							</Box>

							<Box
								component="td"
								sx={{
									px: 1.75,
									py: 0.9,
									whiteSpace: "nowrap",
									borderBottom: "1px solid",
									borderColor: "divider",
									fontFamily: codeFont,
									fontSize: "0.72rem",
									color: field.required ? "error.main" : "text.disabled",
								}}
							>
								{field.required ? "required" : "optional"}
							</Box>

							<Box
								component="td"
								sx={{
									px: 1.75,
									py: 0.9,
									color: "text.secondary",
									fontSize: "0.72rem",
									lineHeight: 1.55,
									borderBottom: "1px solid",
									borderColor: "divider",
								}}
							>
								<Notes field={field} codeFont={codeFont} />
							</Box>
						</Box>
					))}
				</Box>
			</Box>
		</Box>
	);
}

function Notes({ field, codeFont }) {
	const notes = [];

	if (field.enum?.length) {
		notes.push(
			<Box key="enum" sx={{ fontFamily: codeFont }}>
				One of: {field.enum.join(" | ")}
			</Box>,
		);
	}
	if (field.digits) {
		notes.push(<Box key="digits">{field.digits} digits, separators allowed</Box>);
	}
	if (field.help) notes.push(<Box key="help">{field.help}</Box>);
	if (!notes.length) {
		return (
			<Typography component="span" sx={{ color: "text.disabled" }}>
				—
			</Typography>
		);
	}

	return <Box sx={{ display: "flex", flexDirection: "column", gap: 0.35 }}>{notes}</Box>;
}

/** A payload seeded from the catalog examples, so the JSON view documents itself. */
function examplePayload(operation) {
	const payload = {};
	(operation?.fields ?? []).forEach((field) => {
		if (field.example !== undefined && field.example !== null) {
			payload[field.name] = field.example;
		}
	});
	return payload;
}

function parseJsonPayload(text) {
	const trimmed = (text ?? "").trim();
	if (!trimmed) return { ok: true, value: {} };

	let parsed;
	try {
		parsed = JSON.parse(trimmed);
	} catch (error) {
		return { ok: false, error: `Invalid JSON — ${error.message}` };
	}

	if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
		return { ok: false, error: "The payload must be a JSON object." };
	}

	return { ok: true, value: parsed };
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
	const [jsonText, setJsonText] = useState(() =>
		JSON.stringify(examplePayload(operation), null, 2),
	);
	const [inputMode, setInputMode] = useState("form");
	const [jsonError, setJsonError] = useState("");
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

	/** Switching modes carries the current payload across in both directions. */
	const handleModeChange = (_event, next) => {
		if (!next || next === inputMode) return;

		if (next === "json") {
			// Show the real values if anything is filled in, otherwise the
			// documented example so the shape is never an empty object.
			const current = valuesToPayload(operation, values);
			setJsonText(
				JSON.stringify(
					Object.keys(current).length ? current : examplePayload(operation),
					null,
					2,
				),
			);
			setJsonError("");
		} else {
			const parsed = parseJsonPayload(jsonText);
			if (!parsed.ok) {
				// Don't silently discard the edit by bouncing back.
				setJsonError(parsed.error);
				return;
			}
			setValues(payloadToValues(operation, parsed.value));
			setJsonError("");
			setErrors({});
		}

		setInputMode(next);
	};

	/** Field-level checks, run against whichever mode is active. */
	const validate = (payload) => {
		const nextErrors = {};

		(operation?.fields ?? []).forEach((field) => {
			const raw = payload[field.name];
			const text = raw == null ? "" : String(raw).trim();

			if (field.required && !text) {
				nextErrors[field.name] = `${field.label} is required.`;
				return;
			}

			// Mirror the upstream digit rules. The service validates these with
			// a pydantic validator whose error path returns 500, so catching it
			// here keeps a typo from becoming a server error.
			if (field.digits && text) {
				const digits = text.replace(/\D/g, "");
				if (!digits) {
					nextErrors[field.name] = `${field.label} must contain digits.`;
				} else if (digits.length !== field.digits) {
					nextErrors[field.name] = `${field.label} must be exactly ${field.digits} digits.`;
				}
			}
		});

		return nextErrors;
	};

	const handleSubmit = () => {
		let payload;

		if (inputMode === "json") {
			const parsed = parseJsonPayload(jsonText);
			if (!parsed.ok) {
				setJsonError(parsed.error);
				return;
			}
			setJsonError("");
			payload = parsed.value;

			const fieldErrors = validate(payload);
			if (Object.keys(fieldErrors).length > 0) {
				// Reflect them on the form so the user can see which key is wrong.
				setValues(payloadToValues(operation, payload));
				setInputMode("form");
				setErrors(fieldErrors);
				return;
			}
		} else {
			payload = valuesToPayload(operation, values);

			const fieldErrors = validate(payload);
			if (Object.keys(fieldErrors).length > 0) {
				setErrors(fieldErrors);
				return;
			}
		}

		setErrors({});
		onSubmit({ payload, correlationId: correlationId.trim() });
	};

	const handleReset = () => {
		const fresh = buildInitialValues(operation);
		setValues(fresh);
		setErrors({});
		setJsonError("");
		setJsonText(JSON.stringify(examplePayload(operation), null, 2));
		setCorrelationId("");
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
						<ToggleButtonGroup
							value={inputMode}
							exclusive
							onChange={handleModeChange}
							size="small"
							sx={{
								mb: 1.75,
								"& .MuiToggleButton-root": {
									fontSize: "0.72rem",
									px: 1.5,
									py: 0.4,
									gap: 0.75,
									textTransform: "none",
								},
							}}
						>
							{INPUT_MODES.map((mode) => (
								<ToggleButton key={mode.id} value={mode.id}>
									{mode.icon}
									{mode.label}
								</ToggleButton>
							))}
						</ToggleButtonGroup>

						{inputMode === "json" ? (
							<>
								{jsonError ? (
									<Alert severity="error" variant="outlined" sx={{ mb: 1.5 }}>
										{jsonError}
									</Alert>
								) : null}
								<SchemaTable operation={operation} codeFont={codeFont} />

								<TextField
									fullWidth
									multiline
									minRows={10}
									maxRows={26}
									value={jsonText}
									onChange={(event) => {
										setJsonText(event.target.value);
										setJsonError("");
									}}
									spellCheck={false}
									sx={{
										"& textarea": {
											fontFamily: codeFont,
											fontSize: "0.76rem",
											lineHeight: 1.65,
										},
									}}
								/>
								<Typography
									variant="caption"
									sx={{ display: "block", color: "text.disabled", mt: 1 }}
								>
									Any field the endpoint accepts can be added here, including ones
									with no input box.
								</Typography>
							</>
						) : (
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
												<FormControl
													fullWidth
													size="small"
													error={Boolean(errors[field.name])}
												>
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
														"& input": {
															fontFamily: codeFont,
															fontSize: "0.78rem",
														},
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
						)}

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
									onClick={handleReset}
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