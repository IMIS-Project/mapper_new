import {
	Add,
	AutoFixHigh,
	ClearAll,
	Close,
	Link as LinkIcon,
	ModeEditOutline,
	RocketLaunch,
} from "@mui/icons-material";
import {
	Alert,
	Autocomplete,
	Box,
	Button,
	Card,
	Chip,
	CircularProgress,
	IconButton,
	MenuItem,
	TextField,
	ToggleButton,
	ToggleButtonGroup,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApiQuery } from "../../hooks/useApi";
import { getEndpoints } from "../../services/endpointService";
import MethodChip from "../common/MethodChip";

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];

let rowSeed = 0;
const createRow = () => ({ id: `hdr-${(rowSeed += 1)}`, key: "", value: "" });

function parseJsonObject(text) {
	const trimmed = text.trim();
	if (!trimmed) return { ok: true, value: {} };
	try {
		const value = JSON.parse(trimmed);
		if (value === null || typeof value !== "object" || Array.isArray(value)) {
			return { ok: false, error: "Request data must be a JSON object." };
		}
		return { ok: true, value };
	} catch (error) {
		return { ok: false, error: `Invalid JSON — ${error.message}` };
	}
}

function normalizeUrl(value) {
	return String(value ?? "")
		.trim()
		.replace(/\/+$/, "")
		.toLowerCase();
}

function findEndpointForUrl(url, options) {
	const needle = normalizeUrl(url);
	if (!needle || !Array.isArray(options) || options.length === 0) return null;

	let match = options.find(
		(option) => normalizeUrl(option.target_api_url) === needle,
	);
	if (match) return match;

	match = options.find((option) => {
		const stored = normalizeUrl(option.target_api_url);
		return stored && needle.endsWith(stored);
	});
	if (match) return match;

	if (needle.startsWith("/")) {
		match = options.find((option) => {
			const stored = normalizeUrl(option.target_api_url);
			return stored && stored.endsWith(needle);
		});
		if (match) return match;
	}

	return null;
}

function StepLabel({ index, children }) {
	const theme = useTheme();

	return (
		<Box
			sx={{
				display: "flex",
				alignItems: "center",
				gap: 1.25,
				mt: 2.75,
				mb: 1.25,
			}}
		>
			<Typography
				className="mono-label"
				sx={{
					color: "primary.main",
					fontSize: "0.58rem",
					letterSpacing: "0.1em",
				}}
			>
				{index}
			</Typography>
			<Typography
				className="mono-label"
				sx={{
					color: "text.disabled",
					fontSize: "0.58rem",
					whiteSpace: "nowrap",
				}}
			>
				{children}
			</Typography>
			<Box
				sx={{
					flex: 1,
					height: "1px",
					background: `linear-gradient(to right, ${theme.palette.divider}, transparent)`,
				}}
			/>
		</Box>
	);
}

function Key({ children }) {
	const theme = useTheme();

	return (
		<Box
			component="kbd"
			sx={{
				fontFamily: theme.typography.fontFamilyCode,
				fontSize: "0.64rem",
				px: 0.7,
				py: 0.25,
				borderRadius: 1,
				border: "1px solid",
				borderColor: "divider",
				backgroundColor: alpha(theme.palette.text.primary, 0.05),
			}}
		>
			{children}
		</Box>
	);
}

export default function GatewayTester({ onSend, loading = false }) {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;

	const [mode, setMode] = useState("endpoint");
	const [selectedEndpoint, setSelectedEndpoint] = useState(null);
	const [targetUrl, setTargetUrl] = useState("");
	const [targetMethod, setTargetMethod] = useState("POST");
	const [endpointId, setEndpointId] = useState("");
	const [requestDataText, setRequestDataText] = useState("");
	const [headerRows, setHeaderRows] = useState([createRow()]);
	const [fieldErrors, setFieldErrors] = useState({});
	const [dataError, setDataError] = useState("");

	const endpointIdManual = useRef(false);

	const endpointsQuery = useApiQuery(["endpoints"], getEndpoints, {
		staleTime: 60_000,
	});

	const endpoints = useMemo(() => {
		const data = endpointsQuery.data;
		if (Array.isArray(data)) return data;
		if (Array.isArray(data?.items)) return data.items;
		if (Array.isArray(data?.data)) return data.data;
		return [];
	}, [endpointsQuery.data]);

	const handleEndpointPick = useCallback((endpoint) => {
		setSelectedEndpoint(endpoint);
		endpointIdManual.current = false;
		if (!endpoint) return;
		setTargetUrl(endpoint.target_api_url ?? "");
		setTargetMethod(String(endpoint.method ?? "POST").toUpperCase());
		setEndpointId(String(endpoint.id ?? ""));
		setFieldErrors((prev) => ({
			...prev,
			endpointId: "",
			targetUrl: "",
			targetMethod: "",
		}));
	}, []);

	const filterEndpoints = useCallback((options, { inputValue }) => {
		const needle = inputValue.trim().toLowerCase();
		if (!needle) return options;
		return options.filter((option) =>
			`${option.endpoint_code ?? ""} ${option.method ?? ""} ${option.target_api_url ?? ""} ${
				option.source_api_url ?? ""
			}`
				.toLowerCase()
				.includes(needle),
		);
	}, []);

	useEffect(() => {
		if (!targetUrl.trim() || endpoints.length === 0) return;
		if (endpointIdManual.current) return;

		const match = findEndpointForUrl(targetUrl, endpoints);
		if (!match) return;
		if (String(match.id ?? "") === endpointId) return;

		setSelectedEndpoint(match);
		setEndpointId(String(match.id ?? ""));
		setTargetMethod(String(match.method ?? "POST").toUpperCase());
		setFieldErrors((prev) => ({
			...prev,
			endpointId: "",
			targetUrl: "",
			targetMethod: "",
		}));
	}, [targetUrl, endpoints, endpointId]);

	const updateRow = useCallback((id, patch) => {
		setHeaderRows((rows) =>
			rows.map((row) => (row.id === id ? { ...row, ...patch } : row)),
		);
	}, []);

	const removeRow = useCallback((id) => {
		setHeaderRows((rows) => rows.filter((row) => row.id !== id));
	}, []);

	const addRow = useCallback(() => {
		setHeaderRows((rows) => [...rows, createRow()]);
	}, []);

	const handleFormat = useCallback(() => {
		const parsed = parseJsonObject(requestDataText);
		if (!parsed.ok) {
			setDataError(parsed.error);
			return;
		}
		setDataError("");
		setRequestDataText(JSON.stringify(parsed.value, null, 2));
	}, [requestDataText]);

	const handleClear = useCallback(() => {
		setSelectedEndpoint(null);
		setTargetUrl("");
		setTargetMethod("POST");
		setEndpointId("");
		endpointIdManual.current = false;
		setRequestDataText("");
		setHeaderRows([createRow()]);
		setFieldErrors({});
		setDataError("");
	}, []);

	const handleSend = useCallback(() => {
		if (loading) return;

		const errors = {};
		const url = targetUrl.trim();
		if (!url) errors.targetUrl = "External URL is required.";
		else if (!/^(https?:\/\/|\/)/i.test(url)) {
			errors.targetUrl =
				'Use an absolute URL (http:// or https://) or a registered path starting with "/".';
		}

		if (!targetMethod) errors.targetMethod = "Select an HTTP method.";

		const id = endpointId.trim();
		if (!id) errors.endpointId = "Choose an endpoint or paste its UUID.";

		const parsed = parseJsonObject(requestDataText);
		if (!parsed.ok) errors.requestData = parsed.error;

		const headerMap = {};
		let headerError = "";
		headerRows.forEach((row) => {
			const name = row.key.trim();
			const value = String(row.value ?? "");
			if (!name && !value.trim()) return;
			if (!name) {
				headerError = "Every header row needs a name.";
				return;
			}
			headerMap[name] = value;
		});
		if (headerError) errors.headers = headerError;

		setFieldErrors(errors);
		setDataError(parsed.ok ? "" : parsed.error);
		if (Object.keys(errors).length > 0) return;

		onSend?.({
			targetUrl: url,
			targetMethod,
			requestData: parsed.value,
			headers: headerMap,
			endpointId: id,
		});
	}, [
		loading,
		targetUrl,
		targetMethod,
		endpointId,
		requestDataText,
		headerRows,
		onSend,
	]);

	const handleKeyDown = useCallback(
		(event) => {
			if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
				event.preventDefault();
				handleSend();
			}
		},
		[handleSend],
	);

	const endpointsError = endpointsQuery.isError;
	const noEndpoints =
		!endpointsQuery.isLoading && !endpointsError && endpoints.length === 0;

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
			{}
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
				<Box sx={{ flex: 1, minWidth: 160 }}>
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", fontSize: "0.55rem" }}
					>
						Request builder
					</Typography>
					<Typography variant="subtitle1">Compose the call</Typography>
				</Box>

				<ToggleButtonGroup
					size="small"
					exclusive
					value={mode}
					onChange={(_event, value) => {
						if (value) setMode(value);
					}}
					aria-label="External URL selection mode"
				>
					<ToggleButton
						value="endpoint"
						sx={{
							px: 1.4,
							py: 0.35,
							fontSize: "0.7rem",
							fontWeight: 600,
							gap: 0.75,
						}}
					>
						<LinkIcon sx={{ fontSize: 14 }} />
						Mapped
					</ToggleButton>
					<ToggleButton
						value="manual"
						sx={{
							px: 1.4,
							py: 0.35,
							fontSize: "0.7rem",
							fontWeight: 600,
							gap: 0.75,
						}}
					>
						<ModeEditOutline sx={{ fontSize: 14 }} />
						Manual
					</ToggleButton>
				</ToggleButtonGroup>
			</Box>

			{}
			<Box
				component="form"
				noValidate
				onSubmit={(event) => event.preventDefault()}
				onKeyDown={handleKeyDown}
				sx={{ p: 2.25 }}
			>
				<StepLabel index="01">External</StepLabel>

				{mode === "endpoint" ? (
					<>
						<Autocomplete
							options={endpoints}
							value={selectedEndpoint}
							onChange={(_event, value) => handleEndpointPick(value)}
							getOptionLabel={(option) =>
								option?.endpoint_code || option?.id || ""
							}
							isOptionEqualToValue={(a, b) => a?.id === b?.id}
							filterOptions={filterEndpoints}
							loading={endpointsQuery.isLoading}
							size="small"
							noOptionsText="No endpoints match"
							renderInput={(params) => (
								<TextField
									{...params}
									label="Endpoint"
									placeholder="Search by code, method or URL"
								/>
							)}
							renderOption={(props, option) => {
								const { key, ...optionProps } = props;
								return (
									<Box
										component="li"
										key={key}
										{...optionProps}
										sx={{
											display: "flex",
											gap: 1,
											alignItems: "center",
											minWidth: 0,
										}}
									>
										<MethodChip method={option.method} sx={{ flexShrink: 0 }} />
										<Typography
											variant="body2"
											noWrap
											sx={{
												fontWeight: 600,
												fontFamily: codeFont,
												fontSize: "0.76rem",
											}}
										>
											{option.endpoint_code || "untitled"}
										</Typography>
										<Typography
											variant="caption"
											noWrap
											sx={{
												color: "text.disabled",
												fontFamily: codeFont,
												minWidth: 0,
											}}
										>
											{option.target_api_url}
										</Typography>
									</Box>
								);
							}}
						/>

						{endpointsError ? (
							<Alert severity="warning" sx={{ mt: 1.25, py: 0.25 }}>
								Could not load endpoints — check the API connection or switch to
								manual mode.
							</Alert>
						) : null}
						{noEndpoints ? (
							<Typography
								variant="caption"
								sx={{ display: "block", mt: 1, color: "text.disabled" }}
							>
								No endpoints registered yet — create a mapping first, or switch
								to manual mode.
							</Typography>
						) : null}

						{selectedEndpoint ? (
							<Box
								sx={{
									mt: 1.25,
									px: 1.5,
									py: 1,
									display: "flex",
									alignItems: "center",
									gap: 1.25,
									flexWrap: "wrap",
									borderRadius: 2,
									border: "1px dashed",
									borderColor: "divider",
								}}
							>
								<Typography
									className="mono-label"
									sx={{ color: "text.disabled", fontSize: "0.52rem" }}
								>
									Internal
								</Typography>
								<Typography
									sx={{
										fontFamily: codeFont,
										fontSize: "0.72rem",
										color: "text.secondary",
										wordBreak: "break-all",
									}}
								>
									{selectedEndpoint.source_api_url}
								</Typography>
								{selectedEndpoint.is_active === false ? (
									<Chip
										label="inactive"
										size="small"
										sx={{
											height: 20,
											fontSize: "0.62rem",
											color: "warning.main",
											backgroundColor: alpha(theme.palette.warning.main, 0.12),
											border: `1px solid ${alpha(theme.palette.warning.main, 0.35)}`,
										}}
									/>
								) : null}
							</Box>
						) : null}
					</>
				) : null}

				<Box
					sx={{
						display: "flex",
						gap: 1.25,
						mt: mode === "endpoint" ? 1.75 : 0,
						flexWrap: { xs: "wrap", sm: "nowrap" },
					}}
				>
					<TextField
						fullWidth
						size="small"
						label="External URL"
						placeholder="/ref_crp_beneficiary"
						value={targetUrl}
						onChange={(event) => {
							setTargetUrl(event.target.value);

							endpointIdManual.current = false;
							if (fieldErrors.targetUrl)
								setFieldErrors((prev) => ({ ...prev, targetUrl: "" }));
						}}
						error={Boolean(fieldErrors.targetUrl)}
						helperText={
							fieldErrors.targetUrl ||
							"Absolute URL or registered path — auto-maps to its endpoint."
						}
						slotProps={{
							input: { sx: { fontFamily: codeFont, fontSize: "0.78rem" } },
						}}
					/>
					<TextField
						select
						size="small"
						label="Method"
						value={targetMethod}
						onChange={(event) => setTargetMethod(event.target.value)}
						error={Boolean(fieldErrors.targetMethod)}
						sx={{
							width: 126,
							flexShrink: 0,
							"& .MuiSelect-select": {
								fontFamily: codeFont,
								fontSize: "0.78rem",
								fontWeight: 600,
							},
						}}
					>
						{METHODS.map((method) => (
							<MenuItem
								key={method}
								value={method}
								sx={{
									fontFamily: codeFont,
									fontSize: "0.78rem",
									fontWeight: 600,
								}}
							>
								{method}
							</MenuItem>
						))}
					</TextField>
				</Box>

				<TextField
					fullWidth
					size="small"
					label="Endpoint ID"
					placeholder="00000000-0000-0000-0000-000000000000"
					value={endpointId}
					onChange={(event) => {
						endpointIdManual.current = true;
						setEndpointId(event.target.value);
						if (fieldErrors.endpointId)
							setFieldErrors((prev) => ({ ...prev, endpointId: "" }));
					}}
					disabled={mode === "endpoint" && Boolean(selectedEndpoint)}
					error={Boolean(fieldErrors.endpointId)}
					helperText={
						fieldErrors.endpointId ||
						(mode === "endpoint"
							? "Auto-filled from the selected endpoint."
							: "Paste the UUID, or just type the external URL above to auto-map.")
					}
					slotProps={{
						input: { sx: { fontFamily: codeFont, fontSize: "0.74rem" } },
					}}
					sx={{ mt: 0.5 }}
				/>

				<StepLabel index="02">Request data</StepLabel>

				<Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.75 }}>
					<Box sx={{ flex: 1 }} />
					<Tooltip title="Validate and format">
						<Button
							size="small"
							onClick={handleFormat}
							startIcon={<AutoFixHigh sx={{ fontSize: 15 }} />}
							sx={{
								minWidth: 0,
								px: 1.1,
								py: 0.35,
								fontSize: "0.68rem",
								color: "text.secondary",
							}}
						>
							Pretty print
						</Button>
					</Tooltip>
				</Box>

				<TextField
					fullWidth
					multiline
					minRows={7}
					maxRows={16}
					value={requestDataText}
					onChange={(event) => {
						setRequestDataText(event.target.value);
						if (dataError) setDataError("");
					}}
					placeholder={'{\n  "orderId": "A-1001",\n  "amount": 42.5\n}'}
					error={Boolean(dataError)}
					helperText={
						dataError ||
						"JSON object forwarded as the request payload. Empty input sends {}."
					}
					slotProps={{ htmlInput: { spellCheck: false } }}
					sx={{
						"& textarea": {
							fontFamily: codeFont,
							fontSize: "0.78rem",
							lineHeight: 1.75,
						},
					}}
				/>

				<StepLabel index="03">Custom headers</StepLabel>

				{headerRows.map((row) => (
					<Box
						key={row.id}
						sx={{ display: "flex", gap: 1, mb: 1, alignItems: "flex-start" }}
					>
						<TextField
							size="small"
							placeholder="Header name"
							value={row.key}
							onChange={(event) => {
								updateRow(row.id, { key: event.target.value });
								if (fieldErrors.headers)
									setFieldErrors((prev) => ({ ...prev, headers: "" }));
							}}
							sx={{
								flex: 1,
								minWidth: 120,
								"& input": { fontFamily: codeFont, fontSize: "0.74rem" },
							}}
						/>
						<TextField
							size="small"
							placeholder="Value"
							value={row.value}
							onChange={(event) =>
								updateRow(row.id, { value: event.target.value })
							}
							sx={{
								flex: 1.6,
								minWidth: 140,
								"& input": { fontFamily: codeFont, fontSize: "0.74rem" },
							}}
						/>
						<Tooltip title="Remove header">
							<IconButton
								size="small"
								aria-label="Remove header"
								onClick={() => removeRow(row.id)}
								sx={{
									mt: 0.25,
									color: "text.disabled",
									"&:hover": { color: "error.main" },
								}}
							>
								<Close sx={{ fontSize: 17 }} />
							</IconButton>
						</Tooltip>
					</Box>
				))}

				{fieldErrors.headers ? (
					<Typography
						variant="caption"
						sx={{ display: "block", mb: 0.75, color: "error.main" }}
					>
						{fieldErrors.headers}
					</Typography>
				) : null}

				<Button
					size="small"
					onClick={addRow}
					startIcon={<Add sx={{ fontSize: 16 }} />}
					sx={{
						minWidth: 0,
						px: 1.1,
						py: 0.35,
						fontSize: "0.7rem",
						color: "text.secondary",
					}}
				>
					Add header
				</Button>

				{}
				<Box
					sx={{
						display: "flex",
						alignItems: "center",
						gap: 1.25,
						mt: 3,
						pt: 2,
						flexWrap: "wrap",
						borderTop: "1px solid",
						borderColor: "divider",
					}}
				>
					<Button
						variant="contained"
						onClick={handleSend}
						disabled={loading}
						startIcon={
							loading ? (
								<CircularProgress size={15} thickness={5} color="inherit" />
							) : (
								<RocketLaunch sx={{ fontSize: 17 }} />
							)
						}
						sx={{ px: 2.4, py: 0.85 }}
					>
						{loading ? "Sending…" : "Send request"}
					</Button>
					<Button
						onClick={handleClear}
						disabled={loading}
						startIcon={<ClearAll sx={{ fontSize: 17 }} />}
						sx={{ color: "text.secondary" }}
					>
						Clear
					</Button>
					<Box sx={{ flex: 1 }} />
					<Typography
						variant="caption"
						sx={{
							display: "flex",
							alignItems: "center",
							gap: 0.6,
							color: "text.disabled",
							whiteSpace: "nowrap",
						}}
					>
						<Key>Ctrl</Key> + <Key>Enter</Key>
					</Typography>
				</Box>
			</Box>
		</Card>
	);
}
