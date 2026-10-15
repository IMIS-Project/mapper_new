import { AccountBalance, DeleteSweep, History, Token as TokenIcon } from "@mui/icons-material";
import { Alert, Box, Card, Chip, IconButton, Tooltip, Typography } from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useCallback, useEffect, useMemo, useState } from "react";

import MethodChip from "../components/common/MethodChip";
import StatusChip from "../components/common/StatusChip";
import BankCallViewer from "../components/bank/BankCallViewer";
import BankOperationForm from "../components/bank/BankOperationForm";
import { TOKEN_FLOW_LABELS } from "../components/bank/bankConstants";
import { useApiMutation, useApiQuery } from "../hooks/useApi";
import {
	callBankOperation,
	extractBankToken,
	extractTokenExpiry,
	getBankConfig,
	getBankOperations,
} from "../services/bankService";

const HISTORY_LIMIT = 8;

function formatClock(timestamp) {
	if (!timestamp) return "";
	const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
	if (Number.isNaN(date.getTime())) return "";
	return date.toLocaleTimeString([], { hour12: false });
}

function maskToken(value) {
	const text = String(value ?? "");
	if (text.length <= 12) return "••••••";
	return `${text.slice(0, 6)}…${text.slice(-4)}`;
}

/**
 * A wall clock that ticks on an interval. Reading Date.now() straight from
 * render is impure, so the initial value starts null and is filled by the
 * effect on mount.
 */
function useNow(intervalMs = 30_000) {
	const [now, setNow] = useState(null);

	useEffect(() => {
		const tick = () => setNow(Date.now());
		tick();
		const id = window.setInterval(tick, intervalMs);
		return () => window.clearInterval(id);
	}, [intervalMs]);

	return now;
}

/** Turn a thrown axios error into the same shape the backend would have sent. */
function toErrorResult(error) {
	const data = error?.response?.data ?? null;
	let message = error?.message || "The request could not be completed.";

	const detail = data?.detail;
	if (Array.isArray(detail)) {
		message = detail.map((item) => item?.msg ?? JSON.stringify(item)).join(" · ");
	} else if (typeof detail === "string" && detail) {
		message = detail;
	}

	return {
		success: false,
		status_code: error?.response?.status ?? null,
		data,
		error: message,
		response_time_ms: null,
		request_headers: null,
		response_headers: null,
		token_flow: null,
		token_source: null,
		correlation_id: null,
	};
}

function TokenSlot({ label, flowLabel, token, accent }) {
	const theme = useTheme();
	const now = useNow();

	const expired =
		now != null &&
		token?.expiresAt != null &&
		token.expiresAt * 1000 <= now;

	return (
		<Box
			sx={{
				flex: "1 1 280px",
				minWidth: 0,
				px: 2,
				py: 1.5,
				borderRadius: 2.5,
				border: "1px solid",
				borderColor: token ? alpha(accent, 0.4) : "divider",
				backgroundColor: token
					? alpha(accent, theme.palette.mode === "dark" ? 0.12 : 0.06)
					: "transparent",
			}}
		>
			<Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
				<TokenIcon sx={{ fontSize: 16, color: token ? accent : "text.disabled" }} />
				<Typography
					variant="body2"
					sx={{ fontWeight: 600, color: token ? "text.primary" : "text.secondary" }}
				>
					{label}
				</Typography>
				<Box sx={{ flex: 1 }} />
				{token ? (
					expired ? (
						<StatusChip status="pending" size="small" sx={{ fontSize: "0.65rem" }} />
					) : (
						<StatusChip status="success" size="small" sx={{ fontSize: "0.65rem" }} />
					)
				) : null}
			</Box>

			<Typography
				className="mono-label"
				sx={{ display: "block", color: "text.disabled", fontSize: "0.52rem", mt: 0.5 }}
			>
				{flowLabel}
			</Typography>

			{token ? (
				<>
					<Typography
						sx={{
							display: "block",
							fontFamily: theme.typography.fontFamilyCode,
							fontSize: "0.74rem",
							mt: 0.75,
							wordBreak: "break-all",
						}}
					>
						{maskToken(token.value)}
					</Typography>
					<Typography
						variant="caption"
						sx={{ display: "block", color: "text.secondary", mt: 0.35 }}
					>
						Captured {token.capturedLabel}
						{token.expiresAt
							? ` · expires ${formatClock(token.expiresAt * 1000)}`
							: ""}
					</Typography>
				</>
			) : (
				<Typography
					variant="caption"
					sx={{ display: "block", color: "text.disabled", mt: 0.75, fontStyle: "italic" }}
				>
					Not captured yet — run the token step to populate it.
				</Typography>
			)}
		</Box>
	);
}

function HistoryRow({ entry, active, onSelect }) {
	const theme = useTheme();
	const code = entry.response?.status_code ?? null;
	const tone =
		code == null
			? theme.palette.text.disabled
			: code < 300
				? theme.palette.success.main
				: code < 400
					? theme.palette.info.main
					: code < 500
						? theme.palette.warning.main
						: theme.palette.error.main;
	const ok = entry.response?.success !== false && !entry.response?.error;

	return (
		<Box
			role="button"
			tabIndex={0}
			onClick={() => onSelect(entry)}
			onKeyDown={(event) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					onSelect(entry);
				}
			}}
			sx={{
				display: "flex",
				alignItems: "center",
				gap: 1.25,
				px: 2.25,
				py: 1,
				cursor: "pointer",
				borderTop: "1px solid",
				borderColor: "divider",
				backgroundColor: active
					? alpha(theme.palette.primary.main, 0.06)
					: "transparent",
				"&:hover": { backgroundColor: alpha(theme.palette.primary.main, 0.045) },
			}}
		>
			<MethodChip method="POST" size="small" />
			<Typography
				sx={{
					width: 44,
					flexShrink: 0,
					fontFamily: theme.typography.fontFamilyCode,
					fontSize: "0.75rem",
					fontWeight: 600,
					color: tone,
				}}
			>
				{code ?? "—"}
			</Typography>
			<Typography
				variant="body2"
				noWrap
				sx={{
					flex: 1,
					minWidth: 0,
					fontFamily: theme.typography.fontFamilyCode,
					fontSize: "0.73rem",
					color: "text.secondary",
				}}
			>
				{entry.operationLabel}
			</Typography>
			<Typography
				sx={{
					flexShrink: 0,
					display: { xs: "none", md: "block" },
					fontFamily: theme.typography.fontFamilyCode,
					fontSize: "0.68rem",
					color: "text.disabled",
				}}
			>
				{formatClock(entry.timestamp)}
			</Typography>
			<StatusChip status={ok ? "success" : "failed"} size="small" />
		</Box>
	);
}

export default function BankApiPage() {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;

	const [selectedGroup, setSelectedGroup] = useState("token");
	const [selectedId, setSelectedId] = useState(null);
	const [tokens, setTokens] = useState({});
	const [activeCall, setActiveCall] = useState(null);
	const [history, setHistory] = useState([]);
	const [chainingStep, setChainingStep] = useState(null);
	const [chainError, setChainError] = useState(null);

	const operationsQuery = useApiQuery(["bank-operations"], getBankOperations, {
		staleTime: 300_000,
	});
	const configQuery = useApiQuery(["bank-config"], getBankConfig, { staleTime: 300_000 });

	const operations = useMemo(() => {
		const data = operationsQuery.data;
		if (Array.isArray(data)) return data;
		if (Array.isArray(data?.operations)) return data.operations;
		return [];
	}, [operationsQuery.data]);

	const config = configQuery.data ?? null;

	// Derive the selection so the first operation shows as soon as the
	// catalog loads, without an effect round-trip.
	const operation = useMemo(
		() => operations.find((op) => op.id === selectedId) ?? operations[0] ?? null,
		[operations, selectedId],
	);

	const callMutation = useApiMutation(callBankOperation);
	const loading = callMutation.isPending;

	const handleSelectOperation = useCallback((op) => {
		setSelectedId(op.id);
	}, []);

	// Switching groups also moves the selection, otherwise the form would keep
	// rendering an operation from the group the user just left.
	const handleGroupChange = useCallback(
		(groupId) => {
			setSelectedGroup(groupId);
			const first = operations.find((op) => op.group === groupId);
			if (first) setSelectedId(first.id);
		},
		[operations],
	);

	/** Run one operation, capture any token it returns, and record the call. */
	const runOperation = useCallback(
		async (op, { payload, correlationId, bankToken, silent = false } = {}) => {
			if (!op) return null;

			const resolvedToken = op.tokenHeader
				? (bankToken ?? tokens[op.tokenFlow]?.value)
				: undefined;

			let response;
			try {
				response = await callMutation.mutateAsync({
					operationId: op.id,
					payload: payload ?? {},
					correlationId: correlationId || undefined,
					bankToken: resolvedToken || undefined,
				});
			} catch (error) {
				response = toErrorResult(error);
			}

			const stamp = new Date();
			const call = {
				id: stamp.getTime(),
				operationId: op.id,
				operationLabel: op.label,
				operation: op,
				response,
				timestamp: stamp,
			};
			if (!silent) setActiveCall(call);
			setHistory((prev) => [call, ...prev].slice(0, HISTORY_LIMIT));

			// Capture the token a successful token step returned, so the next
			// step in the chain can reuse it.
			let captured = null;
			if (op.tokenOutcome && response?.success !== false) {
				const value = extractBankToken(op, response.data);
				if (value) {
					captured = {
						value,
						expiresAt: extractTokenExpiry(op, response.data),
						capturedLabel: formatClock(stamp),
					};
					setTokens((prev) => ({ ...prev, [op.tokenFlow]: captured }));
				}
			}

			return { ...call, token: captured };
		},
		[callMutation, tokens],
	);

	/**
	 * Authenticate first, then return the raw token for the chained call.
	 *
	 * Returns the bare token, not the {value, expiresAt, ...} record - the
	 * API takes a string.
	 */
	const runAutoChain = useCallback(
		async (op, payload) => {
			const authOp = operations.find((candidate) =>
				candidate.id === op.autoChainOperation,
			);
			if (!authOp) return null;

			const creds = {};
			(op.autoChainCredentials ?? []).forEach((name) => {
				const value = String(payload?.[name] ?? "").trim();
				if (value) creds[name] = value;
			});

			setChainingStep(authOp.label);
			try {
				const result = await runOperation(authOp, {
					payload: creds,
					silent: true,
				});
				return result?.token?.value ?? null;
			} finally {
				setChainingStep(null);
			}
		},
		[operations, runOperation],
	);

	const handleSubmit = useCallback(
		async ({ payload, correlationId }) => {
			if (!operation) return;

			let bankToken = tokens[operation.tokenFlow]?.value;

			if (operation.autoChain) {
				// Always use the token this run just obtained. Reading it back out
				// of `tokens` would hand back the previous one, because setTokens
				// has not been applied to this closure yet - and Bank Alfalah
				// invalidates the old token on every authenticate.
				bankToken = await runAutoChain(operation, payload);
				if (!bankToken) {
					setChainError(
						`Could not obtain the bank-auth token, so ${operation.label} was not called. Check the Bank Auth step in Recent calls.`,
					);
					return;
				}
			}

			setChainError(null);
			await runOperation(operation, {
				payload,
				correlationId,
				bankToken,
			});
		},
		[operation, runAutoChain, runOperation, tokens],
	);

	/** Used by the "Run Bank Auth to capture a token" shortcut. */
	const handleRunToken = useCallback(async () => {
		const authOp = operations.find((op) => op.id === "bank-auth");
		if (!authOp) return;
		const call = await runOperation(authOp, { payload: {}, correlationId: "" });
		if (call) setSelectedId(authOp.id);
	}, [operations, runOperation]);

	const chainedToken = operation?.tokenHeader ? tokens[operation.tokenFlow] : null;

	const misconfigured = config && !config.base_url;

	return (
		<Box>
			<Box sx={{ mb: 2.5 }}>
				<Typography className="mono-label" sx={{ color: "text.disabled" }}>
					Bank Alfalah · Integration console
				</Typography>
				<Typography variant="h5" sx={{ mt: 0.5 }}>
					Exercise the bank APIs behind IMIS
				</Typography>
				<Typography
					variant="body2"
					sx={{ color: "text.secondary", mt: 0.75, maxWidth: 820 }}
				>
					Two independent token flows reach Bank Alfalah. Token Generation
					issues the OAuth token the C2C endpoints use; Bank Auth issues the
					token the account-opening endpoints use. Run a token step first, then
					chain it into the endpoint that needs it.
				</Typography>
				<Typography
					variant="caption"
					sx={{ display: "block", color: "text.disabled", mt: 0.75, maxWidth: 820 }}
				>
					Calls are authenticated with your own signed-in bearer, forwarded to the
					integration service — no separate token to configure.
				</Typography>
			</Box>

			{misconfigured ? (
				<Alert
					severity="warning"
					variant="outlined"
					sx={{ mb: 2.5 }}
				>
					INTEGRATION_API_BASE_URL is not set on this service, so bank
					calls cannot be routed.
				</Alert>
			) : null}

			{config?.base_url ? (
				<Card
					elevation={0}
					sx={{
						mb: 2.5,
						borderRadius: 3,
						border: "1px solid",
						borderColor: "divider",
					}}
				>
					<Box sx={{ px: 2.25, py: 1.5, display: "flex", alignItems: "center", gap: 1.5, flexWrap: "wrap" }}>
						<AccountBalance sx={{ fontSize: 18, color: "text.secondary" }} />
						<Box sx={{ flex: 1, minWidth: 200 }}>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.55rem" }}
							>
								Integration service
							</Typography>
							<Typography
								sx={{
									fontFamily: codeFont,
									fontSize: "0.78rem",
									wordBreak: "break-all",
								}}
							>
								{config.base_url}
							</Typography>
						</Box>
						<Chip
							label="Session bearer forwarded"
							size="small"
							sx={{
								height: 22,
								fontSize: "0.64rem",
								fontWeight: 600,
								color: theme.palette.success.main,
								backgroundColor: alpha(theme.palette.success.main, 0.12),
							}}
						/>
					</Box>

					<Box
						sx={{
							display: "flex",
							flexWrap: "wrap",
							gap: 1.5,
							px: 2.25,
							pb: 2.25,
						}}
					>
						<TokenSlot
							label="Token Generation"
							flowLabel={TOKEN_FLOW_LABELS["token-generation"]}
							token={tokens["token-generation"]}
							accent={theme.palette.primary.main}
						/>
						<TokenSlot
							label="Bank Auth"
							flowLabel={TOKEN_FLOW_LABELS["bank-auth"]}
							token={tokens["bank-auth"]}
							accent={theme.palette.secondary.main}
						/>
					</Box>
				</Card>
			) : null}

			<Box
				sx={{
					display: "grid",
					gridTemplateColumns: {
						xs: "minmax(0, 1fr)",
						lg: "minmax(0, 10fr) minmax(0, 11fr)",
					},
					gap: 2.5,
					alignItems: "start",
				}}
			>
				<BankOperationForm
					key={operation?.id ?? "none"}
					operations={operations}
					operation={operation}
					selectedGroup={selectedGroup}
					onGroupChange={handleGroupChange}
					onSelectOperation={handleSelectOperation}
					token={chainedToken}
					onRunToken={handleRunToken}
					onSubmit={handleSubmit}
					loading={loading}
					chainingStep={chainingStep}
					chainError={chainError}
				/>

				<Box sx={{ minWidth: 0, position: { lg: "sticky" }, top: { lg: 0 } }}>
					<BankCallViewer
						result={activeCall?.response ?? null}
						operation={activeCall?.operation ?? null}
						timestamp={activeCall?.timestamp ?? null}
						loading={loading}
					/>
				</Box>
			</Box>

			{history.length > 0 ? (
				<Card
					elevation={0}
					sx={{
						mt: 2.5,
						borderRadius: 3,
						border: "1px solid",
						borderColor: "divider",
						overflow: "hidden",
					}}
				>
					<Box
						sx={{
							px: 2.25,
							py: 1.4,
							display: "flex",
							alignItems: "center",
							gap: 1.25,
							borderBottom: "1px solid",
							borderColor: "divider",
						}}
					>
						<History sx={{ fontSize: 18, color: "text.secondary" }} />
						<Typography className="mono-label" sx={{ color: "text.secondary" }}>
							Recent bank calls
						</Typography>
						<Chip
							label={history.length}
							size="small"
							sx={{
								height: 19,
								fontSize: "0.62rem",
								fontWeight: 600,
								fontFamily: codeFont,
								color: "text.secondary",
								backgroundColor: alpha(theme.palette.text.primary, 0.06),
							}}
						/>
						<Box sx={{ flex: 1 }} />
						<Tooltip title="Clear history">
							<IconButton
								size="small"
								aria-label="Clear history"
								onClick={() => setHistory([])}
								sx={{
									color: "text.disabled",
									"&:hover": { color: "error.main" },
								}}
							>
								<DeleteSweep fontSize="small" />
							</IconButton>
						</Tooltip>
					</Box>

					{history.map((entry) => (
						<HistoryRow
							key={entry.id}
							entry={entry}
							active={activeCall?.id === entry.id}
							onSelect={setActiveCall}
						/>
					))}
				</Card>
			) : null}
		</Box>
	);
}