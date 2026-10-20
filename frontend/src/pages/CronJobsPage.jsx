import {
	AccountTree,
	Add,
	CheckCircle,
	Close,
	ContentCopy,
	Done,
	DeleteOutline,
	EditOutlined,
	ErrorOutline,
	History,
	PlayArrow,
	Refresh,
	Schedule,
	Visibility,
} from "@mui/icons-material";
import {
	Alert,
	Autocomplete,
	Box,
	Button,
	Chip,
	CircularProgress,
	Collapse,
	Dialog,
	DialogActions,
	DialogContent,
	DialogTitle,
	Divider,
	IconButton,
	MenuItem,
	Paper,
	Stack,
	Switch,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableRow,
	TextField,
	ToggleButton,
	ToggleButtonGroup,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSnackbar } from "../context/SnackbarContext";
import { useApiMutation, useApiQuery } from "../hooks/useApi";
import MethodChip from "../components/common/MethodChip";
import endpointService from "../services/endpointService";
import scheduledJobService from "../services/scheduledJobService";
import {
	METHODS,
	buildBodySkeleton,
	formatBody,
	formatBytes,
	formatDate,
	formatDuration,
	formatExactTime,
	formatLegBody,
	formatPreciseTime,
	formatRelative,
	getErrorMessage,
	groupParametersByLocation,
	initialJobForm,
	isAbsoluteHttpUrl,
	mappingExternalUrl,
	mappingInternalUrl,
	mergeRows,
	normalizeMappingMethod,
	parameterExternalName,
	parameterInternalName,
	parametersToRows,
	parseMappingRun,
	rowsToHeaders,
	scheduleLabel,
	supportsBody,
} from "../services/scheduledJobConstants";

/** Filter the mapping picker on code, description and both URLs. */
const filterMappings = (options, state) => {
	const needle = String(state?.inputValue || "").trim().toLowerCase();
	if (!needle) return options;
	return options.filter((option) =>
		[option.endpoint_code, option.description, option.source_api_url, option.target_api_url]
			.filter(Boolean)
			.some((field) => String(field).toLowerCase().includes(needle)),
	);
};

export default function CronJobsPage() {
	const theme = useTheme();
	const queryClient = useQueryClient();
	const { showSnackbar } = useSnackbar();
	const [form, setForm] = useState(initialJobForm);
	const [selectedMapping, setSelectedMapping] = useState(null);
	const [mappingParameters, setMappingParameters] = useState([]);
	const [historyJobId, setHistoryJobId] = useState("");
	const [selectedRunId, setSelectedRunId] = useState(null);
	const [saving, setSaving] = useState(false);
	const [actionId, setActionId] = useState("");
	const jobsQuery = useApiQuery(["scheduled-jobs"], scheduledJobService.getScheduledJobs, { refetchInterval: 15000 });
	const runsQuery = useApiQuery(
		["scheduled-runs", historyJobId],
		() => historyJobId ? scheduledJobService.getScheduledJobRuns(historyJobId, 100) : scheduledJobService.getScheduledRuns(100),
		{ refetchInterval: 15000 },
	);
	// Mapping lookup is SELECT-only and only runs while the mapping tab is open.
	const mappingsQuery = useApiQuery(
		["cron-job-mappings"],
		endpointService.listMappings,
		{ enabled: form.sourceMode === "mapping", staleTime: 30000 },
	);
	// Bodies and header sets are only fetched once a run is actually opened,
	// so the polling list stays small.
	const runDetailQuery = useApiQuery(
		["scheduled-run", selectedRunId],
		() => selectedRunId ? scheduledJobService.getScheduledRunDetail(selectedRunId) : Promise.resolve(null),
		{ enabled: selectedRunId !== null, refetchInterval: 15000 },
	);
	const jobs = useMemo(() => jobsQuery.data || [], [jobsQuery.data]);
	const runs = runsQuery.data || [];
	const jobNames = useMemo(() => Object.fromEntries(jobs.map((job) => [job.job_id, job.name || job.job_id])), [jobs]);
	const readError = (error) => getErrorMessage(error, "The scheduler request failed.");
	const updateForm = (key, value) => setForm((previous) => ({ ...previous, [key]: value }));
	const updateHeaderRow = (index, key, value) => setForm((previous) => ({
		...previous,
		headers: previous.headers.map((row, position) => (position === index ? { ...row, [key]: value } : row)),
	}));
	const addHeaderRow = () => setForm((previous) => ({ ...previous, headers: [...previous.headers, { name: "", value: "" }] }));
	const removeHeaderRow = (index) => setForm((previous) => ({ ...previous, headers: previous.headers.filter((_, position) => position !== index) }));

	// Switching between the two registration modes never discards the URL,
	// headers or body already on the form.
	const changeSourceMode = (mode) => {
		setForm((previous) => ({ ...previous, sourceMode: mode }));
		if (mode !== "mapping") {
			setSelectedMapping(null);
			setMappingParameters([]);
		}
	};

	/**
	 * Fill the form from a mapping's parameter rows: the internal URL, method,
	 * name, header placeholders and the JSON body skeleton. The rows are read
	 * only — the mapping itself is never written to.
	 */
	const applyMapping = (mapping, parameters) => {
		const groups = groupParametersByLocation(parameters);
		const method = normalizeMappingMethod(mapping.method);
		setForm((previous) => {
			const next = {
				...previous,
				mappingId: mapping.id,
				method,
				// The job's URL is the internal API, which is also what the
				// backend matches the mapping on.
				url: mappingInternalUrl(mapping),
				name: previous.name.trim() || mapping.endpoint_code || "",
				headers: mergeRows(previous.headers, parametersToRows(groups.HEADER)),
			};
			if (supportsBody(method)) {
				const skeleton = buildBodySkeleton(groups.BODY);
				if (skeleton) next.body = skeleton;
			}
			return next;
		});
	};

	const pickMapping = async (mapping) => {
		if (!mapping) {
			setSelectedMapping(null);
			setMappingParameters([]);
			setForm((previous) => ({ ...previous, mappingId: null }));
			return;
		}
		setSelectedMapping(mapping);
		// The endpoint list already eager-loads the parameter rows. Seed the
		// URL, headers and body straight from them so the form fills as soon
		// as a mapping is picked; only fall back to the dedicated endpoint
		// when the list response did not include any parameters.
		const included = Array.isArray(mapping.parameters)
			? mapping.parameters.filter((parameter) => parameter?.is_active !== false)
			: [];
		setMappingParameters(included);
		applyMapping(mapping, included);
		if (included.length) return;
		try {
			const parameters = (await queryClient.fetchQuery({
				queryKey: ["cron-job-mapping-parameters", mapping.id],
				queryFn: () => endpointService.getParameters(mapping.id),
			})) || [];
			setMappingParameters(parameters);
			applyMapping(mapping, parameters);
		} catch (error) {
			showSnackbar(readError(error), "error");
		}
	};

	const createMutation = useApiMutation(scheduledJobService.createScheduledJob, {
		onSuccess: async () => {
			setSaving(false);
			setForm(initialJobForm);
			setSelectedMapping(null);
			setMappingParameters([]);
			await queryClient.invalidateQueries({ queryKey: ["scheduled-jobs"] });
			showSnackbar("Cron job created", "success");
		},
		onError: (error) => { setSaving(false); showSnackbar(readError(error), "error"); },
	});
	const actionMutation = useApiMutation(
		({ action, job }) => action === "toggle"
			? scheduledJobService.toggleScheduledJob(job.job_id, !job.enabled)
			: action === "run"
				? scheduledJobService.runScheduledJob(job.job_id)
				: scheduledJobService.deleteScheduledJob(job.job_id),
		{
			onSuccess: async (result, variables) => {
				setActionId("");
				await Promise.all([
					queryClient.invalidateQueries({ queryKey: ["scheduled-jobs"] }),
					queryClient.invalidateQueries({ queryKey: ["scheduled-runs"] }),
				]);
				const message = variables.action === "toggle" ? (result.enabled ? "Cron job resumed" : "Cron job paused") : variables.action === "run" ? "Cron job executed" : "Cron job deleted";
				showSnackbar(message, "success");
			},
			onError: (error) => { setActionId(""); showSnackbar(readError(error), "error"); },
		},
	);

	const submit = (event) => {
		event.preventDefault();
		setSaving(true);
		const payload = { url: form.url.trim(), method: form.method, name: form.name.trim() || null };
		if (form.job_id.trim()) payload.job_id = form.job_id.trim();
		payload[form.scheduleType === "interval" ? "interval_seconds" : "cron"] = form.scheduleType === "interval" ? Number.parseInt(form.intervalSeconds, 10) : form.cron.trim();
		const headers = rowsToHeaders(form.headers);
		if (Object.keys(headers).length) payload.headers = headers;
		if (form.body.trim()) payload.body = form.body;
		createMutation.mutate(payload);
	};
	const act = (action, job) => {
		if (action === "delete" && !window.confirm(`Delete “${job.name || job.job_id}”? Past runs will be kept.`)) return;
		setActionId(job.job_id);
		actionMutation.mutate({ action, job });
	};
	const error = jobsQuery.error || runsQuery.error;
	const refreshing = jobsQuery.isFetching || runsQuery.isFetching;

	return (
		<Box>
			<Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 2, flexWrap: "wrap", mb: 2.5 }}>
				<Box sx={{ flex: "1 1 360px" }}>
					<Typography className="mono-label" sx={{ color: "primary.main", mb: 0.75 }}>Automation · Recurring HTTP calls</Typography>
					<Typography variant="h5" sx={{ mb: 0.5 }}>Cron Jobs</Typography>
					<Typography variant="body2" sx={{ color: "text.secondary", maxWidth: 700 }}>Create cron or interval-based API calls. Every execution is retained in the dedicated scheduler SQLite database.</Typography>
				</Box>
				<Stack direction="row" spacing={1} alignItems="center">
					<Chip size="small" label={`${jobs.filter((job) => job.enabled).length} active`} icon={<Schedule fontSize="small" />} sx={{ backgroundColor: alpha(theme.palette.primary.main, 0.1) }} />
					<Tooltip title="Refresh" arrow><span><IconButton onClick={() => { jobsQuery.refetch(); runsQuery.refetch(); }} disabled={refreshing} aria-label="Refresh scheduler data"><Refresh /></IconButton></span></Tooltip>
				</Stack>
			</Box>
			<CreateForm
				form={form}
				saving={saving}
				selectedMapping={selectedMapping}
				mappingParameters={mappingParameters}
				mappings={mappingsQuery.data || []}
				mappingsLoading={mappingsQuery.isLoading}
				mappingsError={mappingsQuery.error}
				onChange={updateForm}
				onSourceModeChange={changeSourceMode}
				onMappingPick={pickMapping}
				onHeaderChange={updateHeaderRow}
				onHeaderAdd={addHeaderRow}
				onHeaderRemove={removeHeaderRow}
				onSubmit={submit}
			/>
			{error ? <Alert severity="error" sx={{ mb: 2 }}>{readError(error)}</Alert> : null}
			<JobTable jobs={jobs} loading={jobsQuery.isLoading} actionId={actionId} onAction={act} />
			<RunTable runs={runs} loading={runsQuery.isLoading} jobNames={jobNames} historyJobId={historyJobId} onHistoryJobChange={setHistoryJobId} onSelectRun={setSelectedRunId} />
			<RunDetailDialog runId={selectedRunId} query={runDetailQuery} jobNames={jobNames} onClose={() => setSelectedRunId(null)} />
		</Box>
	);
}

function CreateForm({
	form,
	saving,
	selectedMapping,
	mappingParameters,
	mappings,
	mappingsLoading,
	mappingsError,
	onChange,
	onSourceModeChange,
	onMappingPick,
	onHeaderChange,
	onHeaderAdd,
	onHeaderRemove,
	onSubmit,
}) {
	const bodyAllowed = supportsBody(form.method);
	const fromMapping = form.sourceMode === "mapping" && Boolean(selectedMapping);
	return <Paper component="form" onSubmit={onSubmit} elevation={0} sx={{ p: { xs: 2, sm: 2.5 }, mb: 2, borderRadius: 3, border: "1px solid", borderColor: "divider" }}>
		<Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}><Add color="primary" /><Typography variant="subtitle1">Create a scheduled request</Typography></Stack>
		<Box sx={{ mb: 2 }}><SourceModeTabs mode={form.sourceMode} onChange={onSourceModeChange} /></Box>
		{form.sourceMode === "mapping" ? <MappingPicker
			mappings={mappings}
			loading={mappingsLoading}
			error={mappingsError}
			selected={selectedMapping}
			parameters={mappingParameters}
			onPick={onMappingPick}
		/> : null}
		<Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", lg: "1.4fr .8fr .6fr 1fr" }, gap: 1.5 }}>
			<TextField
				label={fromMapping ? "Internal API URL" : "API URL"}
				placeholder="https://api.example.com/health"
				value={form.url}
				onChange={(event) => onChange("url", event.target.value)}
				required
				fullWidth
				size="small"
				disabled={fromMapping}
				helperText={fromMapping ? "Picked from the mapping — this is where the external payload is delivered." : undefined}
			/>
			<TextField label="Display name" value={form.name} onChange={(event) => onChange("name", event.target.value)} fullWidth size="small" />
			<TextField select label="Method" value={form.method} onChange={(event) => onChange("method", event.target.value)} fullWidth size="small" disabled={fromMapping}>{METHODS.map((method) => <MenuItem key={method} value={method}>{method}</MenuItem>)}</TextField>
			<TextField label="Job ID (optional)" value={form.job_id} onChange={(event) => onChange("job_id", event.target.value)} fullWidth size="small" />
		</Box>
		<Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "180px 1fr" }, gap: 1.5, mt: 1.5 }}>
			<TextField select label="Schedule type" value={form.scheduleType} onChange={(event) => onChange("scheduleType", event.target.value)} fullWidth size="small"><MenuItem value="interval">Every interval</MenuItem><MenuItem value="cron">Cron expression</MenuItem></TextField>
			{form.scheduleType === "interval" ? <TextField label="Interval in seconds" type="number" inputProps={{ min: 1, step: 1 }} value={form.intervalSeconds} onChange={(event) => onChange("intervalSeconds", event.target.value)} required fullWidth size="small" /> : <TextField label="Cron expression" placeholder="*/5 * * * *" helperText="minute hour day month weekday" value={form.cron} onChange={(event) => onChange("cron", event.target.value)} required fullWidth size="small" />}
		</Box>
		<HeaderEditor rows={form.headers} onChange={onHeaderChange} onAdd={onHeaderAdd} onRemove={onHeaderRemove} />
		{bodyAllowed ? <Box sx={{ mt: 1.5 }}>
			<Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}><Typography variant="subtitle2">Request body</Typography><Typography variant="caption" color="text.secondary">{fromMapping ? "Values for the internal fields, seeded from the mapping. They are renamed to the external field names on the way out." : "Content-Type is inferred from the body unless you set the header yourself."}</Typography></Stack>
			<TextField label="Body" placeholder={'{\n  "example": true\n}'} value={form.body} onChange={(event) => onChange("body", event.target.value)} fullWidth multiline minRows={4} maxRows={14} size="small" className="mono" InputProps={{ sx: { fontFamily: "var(--font-mono)", fontSize: "0.8rem" } }} />
		</Box> : null}
		<Box sx={{ display: "flex", justifyContent: "flex-end", mt: 2 }}><Button type="submit" variant="contained" disabled={saving || !form.url.trim() || (form.sourceMode === "mapping" && !selectedMapping)} startIcon={saving ? <CircularProgress size={15} color="inherit" /> : <Add />}>{fromMapping ? "Create mapped cron job" : "Create cron job"}</Button></Box>
	</Paper>;
}

function SourceModeTabs({ mode, onChange }) {
	return <ToggleButtonGroup
		value={mode}
		exclusive
		size="small"
		onChange={(_event, value) => { if (value) onChange(value); }}
		sx={{ flexWrap: "wrap" }}
	>
		<ToggleButton value="manual" sx={{ gap: 0.75, px: 1.75, fontWeight: 600 }}><EditOutlined fontSize="small" />Manual URL</ToggleButton>
		<ToggleButton value="mapping" sx={{ gap: 0.75, px: 1.75, fontWeight: 600 }}><AccountTree fontSize="small" />From API mapping</ToggleButton>
	</ToggleButtonGroup>;
}

/**
 * Pick an existing mapping. The list, the mapping itself and its parameters
 * are only ever read — nothing is written back to the mapping database.
 */
function MappingPicker({ mappings, loading, error, selected, parameters, onPick }) {
	const options = useMemo(() => [...(mappings || [])]
		.filter((mapping) => mapping?.is_active !== false)
		.sort((a, b) => String(a.endpoint_code || a.id).localeCompare(String(b.endpoint_code || b.id))), [mappings]);
	return <Box sx={{ mb: 2, p: 1.75, borderRadius: 2.5, border: "1px dashed", borderColor: "divider" }}>
		<Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.25 }}><AccountTree color="primary" fontSize="small" /><Typography variant="subtitle2">API mapping</Typography><Typography variant="caption" color="text.secondary">Read-only — the mapping is never modified.</Typography></Stack>
		{error ? <Alert severity="warning" sx={{ mb: 1.25, py: 0.25 }}>{getErrorMessage(error, "Could not load the API mappings.")}</Alert> : null}
		<Autocomplete
			options={options}
			value={selected}
			onChange={(_event, value) => onPick(value)}
			isOptionEqualToValue={(a, b) => a?.id === b?.id}
			getOptionLabel={(option) => String(option?.endpoint_code || option?.id || "")}
			filterOptions={filterMappings}
			loading={loading}
			size="small"
			noOptionsText="No active mappings match"
			renderInput={(params) => <TextField {...params} label="Mapping" placeholder="Search by code, description or URL" />}
			renderOption={(props, option) => {
				const { key, ...optionProps } = props;
				return <Box component="li" key={key} {...optionProps} sx={{ display: "flex", gap: 1, alignItems: "center", minWidth: 0 }}>
					<MethodChip method={option.method} sx={{ flexShrink: 0 }} />
					<Typography variant="body2" noWrap sx={{ fontWeight: 600, fontSize: "0.78rem" }}>{option.endpoint_code || `Mapping #${option.id}`}</Typography>
					<Typography variant="caption" noWrap sx={{ color: "text.disabled", fontFamily: "var(--font-mono)", minWidth: 0 }}>{mappingInternalUrl(option)}</Typography>
				</Box>;
			}}
		/>
		{options.length === 0 && !loading ? <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>No active API mappings exist yet — create one under API Mappings, or switch back to Manual URL.</Typography> : null}
		{selected ? <MappingSummary mapping={selected} parameters={parameters} /> : null}
	</Box>;
}

/**
 * What the job will do, spelled out: the external API is always called first
 * and whatever it returns is forwarded to the internal API unchanged.
 */
function MappingSummary({ mapping, parameters }) {
	const external = mappingExternalUrl(mapping);
	const internal = mappingInternalUrl(mapping);
	const rows = parameters.filter((parameter) => parameterInternalName(parameter));
	return <Box sx={{ mt: 1.5, px: 1.5, py: 1.25, borderRadius: 2, backgroundColor: "action.hover" }}>
		<Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1, flexWrap: "wrap", gap: 1 }}>
			<Typography className="mono-label" color="text.secondary">On every run</Typography>
			<Chip size="small" label="1 · external API" sx={{ height: 22, fontSize: "0.64rem" }} />
			<Chip size="small" label="2 · internal API" sx={{ height: 22, fontSize: "0.64rem" }} />
		</Stack>
		<Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "90px 1fr" }, gap: 0.75, alignItems: "baseline" }}>
			<Typography className="mono-label" color="text.disabled" sx={{ fontSize: "0.52rem" }}>External</Typography>
			<Typography variant="caption" className="mono" sx={{ wordBreak: "break-all" }}>{external || "— not configured —"}</Typography>
			<Typography className="mono-label" color="text.disabled" sx={{ fontSize: "0.52rem" }}>Internal</Typography>
			<Typography variant="caption" className="mono" sx={{ wordBreak: "break-all" }}>{internal || "— not configured —"}</Typography>
		</Box>
		{rows.length ? <Box sx={{ mt: 1.5 }}>
			<Typography className="mono-label" color="text.disabled" sx={{ fontSize: "0.52rem", mb: 0.5 }}>Parameters picked ({rows.length})</Typography>
			<Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
				{rows.map((parameter) => <Chip
					key={parameter.id ?? `${parameterInternalName(parameter)}-${parameterExternalName(parameter)}`}
					size="small"
					variant="outlined"
					label={`${parameterInternalName(parameter)} → ${parameterExternalName(parameter)}`}
					title={`${String(parameter.parameter_type || "BODY").toUpperCase()} parameter`}
					sx={{ height: 20, fontSize: "0.6rem", fontFamily: "var(--font-mono)" }}
				/>)}
			</Box>
		</Box> : null}
		{!external ? <Alert severity="warning" sx={{ mt: 1, py: 0.25 }}>This mapping has no external URL, so the run will be recorded without calling out.</Alert> : null}
		{!isAbsoluteHttpUrl(internal) ? <Alert severity="info" sx={{ mt: 1, py: 0.25 }}>This mapping&rsquo;s internal URL is a path; it is expanded against the mapper&rsquo;s base URL when the external payload is delivered.</Alert> : null}
	</Box>;
}

function HeaderEditor({ rows, onChange, onAdd, onRemove }) {
	return <Box sx={{ mt: 1.5 }}>
		<Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}>
			<Typography variant="subtitle2">Request headers</Typography>
			<Button size="small" onClick={onAdd} startIcon={<Add fontSize="small" />}>Add header</Button>
		</Stack>
		{rows.length === 0 ? <Typography variant="caption" color="text.secondary">No custom headers. Host, Content-Length and connection headers are managed by the scheduler.</Typography> : <Stack spacing={1}>
			{rows.map((row, index) => <Stack key={index} direction="row" spacing={1} alignItems="center">
				<TextField label="Name" value={row.name} onChange={(event) => onChange(index, "name", event.target.value)} placeholder="Authorization" size="small" sx={{ flex: "0 1 260px" }} />
				<TextField label="Value" value={row.value} onChange={(event) => onChange(index, "value", event.target.value)} placeholder="Bearer token" size="small" sx={{ flex: 1 }} />
				<Tooltip title="Remove header"><span><IconButton size="small" onClick={() => onRemove(index)} aria-label={`Remove header ${row.name || index + 1}`}><DeleteOutline fontSize="small" /></IconButton></span></Tooltip>
			</Stack>)}
		</Stack>}
	</Box>;
}

function JobTable({ jobs, loading, actionId, onAction }) {
	return <Paper elevation={0} sx={{ mb: 2, borderRadius: 3, border: "1px solid", borderColor: "divider", overflow: "hidden" }}>
		<Box sx={{ px: 2, py: 1.5, display: "flex", alignItems: "center", gap: 1.25, borderBottom: "1px solid", borderColor: "divider" }}><Schedule sx={{ color: "text.secondary", fontSize: 20 }} /><Typography variant="subtitle2">Scheduled jobs</Typography><Chip size="small" label={jobs.length} /></Box>
		{loading ? <Box sx={{ py: 6, textAlign: "center" }}><CircularProgress size={26} /></Box> : jobs.length === 0 ? <Box sx={{ py: 6, textAlign: "center" }}><Typography variant="body2" color="text.secondary">No cron jobs yet.</Typography></Box> : <TableContainer><Table size="small"><TableHead><TableRow><TableCell>Job</TableCell><TableCell>Schedule</TableCell><TableCell>Next run</TableCell><TableCell>Last result</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead><TableBody>{jobs.map((job) => { const busy = actionId === job.job_id; return <TableRow key={job.job_id} hover><TableCell><Typography variant="body2" fontWeight={600}>{job.name || job.job_id}</Typography><Typography variant="caption" color="text.secondary" className="mono">{job.job_id} · {job.method} · {job.url}</Typography>{job.mapping ? <Tooltip title={`External: ${job.mapping.external_url} → Internal: ${job.mapping.internal_url}`}><Chip size="small" icon={<AccountTree fontSize="small" />} label={`${job.mapping.endpoint_code || `Mapping #${job.mapping.endpoint_id}`} · ${job.mapping.parameter_count} params`} sx={{ mt: 0.5, height: 20, fontSize: "0.62rem" }} /></Tooltip> : null}</TableCell><TableCell><Typography variant="body2" className="mono">{scheduleLabel(job)}</Typography></TableCell><TableCell><Typography variant="body2">{formatDate(job.next_run_time)}</Typography></TableCell><TableCell>{job.last_run_at ? <Chip size="small" color={job.last_success ? "success" : "error"} label={job.last_success ? "Success" : "Failed"} /> : <Typography variant="body2" color="text.disabled">No runs yet</Typography>}<Typography variant="caption" display="block" color="text.secondary">{formatDate(job.last_run_at)}</Typography></TableCell><TableCell align="right"><Switch size="small" checked={job.enabled} disabled={busy} onChange={() => onAction("toggle", job)} inputProps={{ "aria-label": `Toggle ${job.job_id}` }} /><Tooltip title="Run now"><span><IconButton size="small" disabled={busy} onClick={() => onAction("run", job)} aria-label={`Run ${job.job_id} now`}>{busy ? <CircularProgress size={17} /> : <PlayArrow fontSize="small" />}</IconButton></span></Tooltip><Tooltip title="Delete"><span><IconButton size="small" disabled={busy} onClick={() => onAction("delete", job)} aria-label={`Delete ${job.job_id}`}><DeleteOutline fontSize="small" /></IconButton></span></Tooltip></TableCell></TableRow>; })}</TableBody></Table></TableContainer>}
	</Paper>;
}

function RunTable({ runs, loading, jobNames, historyJobId, onHistoryJobChange, onSelectRun }) {
	return <Paper elevation={0} sx={{ borderRadius: 3, border: "1px solid", borderColor: "divider", overflow: "hidden" }}>
		<Box sx={{ px: 2, py: 1.5, display: "flex", alignItems: "center", gap: 1.25, flexWrap: "wrap", borderBottom: "1px solid", borderColor: "divider" }}><History sx={{ color: "text.secondary", fontSize: 20 }} /><Typography variant="subtitle2">Past runs</Typography><Chip size="small" label={runs.length} /><TextField select label="Job" value={historyJobId} onChange={(event) => onHistoryJobChange(event.target.value)} size="small" sx={{ ml: "auto", minWidth: 190 }}><MenuItem value="">All jobs</MenuItem>{Object.entries(jobNames).map(([jobId, name]) => <MenuItem key={jobId} value={jobId}>{name}</MenuItem>)}</TextField><Typography className="mono-label" color="text.disabled">SQLite history</Typography></Box>
		{loading ? <Box sx={{ py: 6, textAlign: "center" }}><CircularProgress size={26} /></Box> : runs.length === 0 ? <Box sx={{ py: 6, textAlign: "center" }}><Typography variant="body2" color="text.secondary">No executions have been recorded yet.</Typography></Box> : <TableContainer><Table size="small"><TableHead><TableRow><TableCell>Timestamp</TableCell><TableCell>Job</TableCell><TableCell>Method</TableCell><TableCell align="center">Status</TableCell><TableCell align="right">Duration</TableCell><TableCell>Error</TableCell><TableCell align="right">Detail</TableCell></TableRow></TableHead><TableBody>{runs.map((run) => <TableRow key={run.id} hover onClick={() => onSelectRun(run.id)} sx={{ cursor: "pointer" }}><TableCell><Tooltip title={`${formatPreciseTime(run.ran_at)} · ${formatExactTime(run.ran_at)}`}><span><Typography variant="body2" className="mono" sx={{ whiteSpace: "nowrap" }}>{formatExactTime(run.ran_at)}</Typography><Typography variant="caption" display="block" color="text.secondary">{formatRelative(run.ran_at)}</Typography></span></Tooltip></TableCell><TableCell>{jobNames[run.job_id] || run.job_id}</TableCell><TableCell className="mono">{run.method}</TableCell><TableCell align="center"><Chip size="small" color={run.success ? "success" : "error"} icon={run.success ? <CheckCircle /> : <ErrorOutline />} label={run.status_code || "Error"} /></TableCell><TableCell align="right" className="mono">{formatDuration(run.duration_ms)}</TableCell><TableCell><Typography variant="caption" color={run.error ? "error.main" : "text.disabled"}>{run.error || "—"}</Typography></TableCell><TableCell align="right"><Tooltip title="View request and response detail"><span><IconButton size="small" onClick={(event) => { event.stopPropagation(); onSelectRun(run.id); }} aria-label={`View detail of run ${run.id}`}><Visibility fontSize="small" /></IconButton></span></Tooltip></TableCell></TableRow>)}</TableBody></Table></TableContainer>}
	</Paper>;
}

/** Shared styling for a captured request/response payload block. */
const BODY_PRE_SX = (theme) => ({
	m: 0,
	p: 2,
	maxHeight: 300,
	overflow: "auto",
	border: "1px solid",
	borderColor: "divider",
	borderRadius: 2,
	backgroundColor: alpha(
		theme.palette.background.default,
		theme.palette.mode === "dark" ? 0.6 : 0.7,
	),
	fontFamily: "var(--font-mono)",
	fontSize: "0.76rem",
	lineHeight: 1.65,
	whiteSpace: "pre-wrap",
	wordBreak: "break-word",
});

/** One leg of a mapping run: which API was called and what came back. */
function MappingLegCard({ step, title, leg, theme, defaultCollapsed = false }) {
	const body = useMemo(() => formatLegBody(leg), [leg]);
	const failed = Boolean(leg?.error) || !(leg?.status_code >= 200 && leg?.status_code < 300);
	const [showBody, setShowBody] = useState(!defaultCollapsed);
	return <Box sx={{ mb: 2 }}>
		<Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }} flexWrap="wrap">
			<Chip size="small" label={step} color={failed ? "error" : "success"} sx={{ height: 20, fontSize: "0.6rem" }} />
			<Typography className="mono-label" color="text.secondary">{title}</Typography>
			{leg?.status_code ? <Chip size="small" color={failed ? "error" : "success"} label={leg.status_code} /> : null}
			{leg?.duration_ms != null ? <Typography variant="caption" color="text.secondary" className="mono">{formatDuration(leg.duration_ms)}</Typography> : null}
		</Stack>
		{leg?.url ? <Typography variant="caption" className="mono" sx={{ display: "block", mb: 0.75, wordBreak: "break-all" }}>{leg.method} {leg.url}</Typography> : null}
		{leg?.error ? <Alert severity="error" sx={{ mb: 1, py: 0.25 }}>{leg.error}</Alert> : null}
		<HeaderTable title="Request headers" headers={leg?.request_headers} empty="No request headers were captured." />
		<HeaderTable title="Response headers" headers={leg?.response_headers} empty="No response headers were captured." />
		{body ? <Box>
			<Button size="small" onClick={() => setShowBody((value) => !value)} sx={{ mb: 0.75 }}>
				{showBody ? "Hide payload" : `Show payload (${formatBytes(body.length)})`}
			</Button>
			<Collapse in={showBody}><Box component="pre" sx={BODY_PRE_SX(theme)}>{body}</Box></Collapse>
		</Box> : <Typography variant="body2" color="text.disabled">No payload was captured for this step.</Typography>}
	</Box>;
}

/**
 * A mapping run has two legs: the external API is called first and its
 * response is then forwarded to the internal API.
 */
function MappingRunDetail({ mappingRun, theme }) {
	const internal = mappingRun.internal;
	const selfContained = Boolean(mappingRun.self_contained);
	const internalFailed = Boolean(internal) && (Boolean(internal.error) || !(internal.status_code >= 200 && internal.status_code < 300));
	return <Box sx={{ mt: 1.5 }}>
		{mappingRun.mapping?.endpoint_code ? <Alert severity="info" sx={{ mb: 1.5, py: 0.25 }}>
			{selfContained ? `Remote-file run for ${mappingRun.mapping.endpoint_code} — the data source is read directly over SFTP (or its read-only HTTP index), with no separate internal API call.` : `Mapped run for ${mappingRun.mapping.endpoint_code} — the external API is called first and its response is forwarded verbatim to the internal API.`}
		</Alert> : null}
		{internalFailed ? <Alert severity="error" sx={{ mb: 1.5, py: 0.25 }}>
			The external data was fetched, but delivery to the internal API failed{internal.error ? ` (${internal.error})` : ""}. That payload is kept for diagnosis and collapsed below; the run is marked failed.
		</Alert> : null}
		<MappingLegCard step="1" title={selfContained ? "Remote file source" : "External API"} leg={mappingRun.external} theme={theme} defaultCollapsed={internalFailed} />
		<Divider sx={{ my: 2 }} />
		{internal ? <MappingLegCard step="2" title="Internal API" leg={internal} theme={theme} /> : selfContained ? <Alert severity="info" sx={{ py: 0.25 }}>Served directly from the remote file source; no internal API delivery was needed.</Alert> : <Alert severity="warning" sx={{ py: 0.25 }}>The internal API was not called because the external call did not succeed.</Alert>}
	</Box>;
}

function HeaderTable({ title, headers, empty }) {
	const entries = Object.entries(headers || {});
	return <Box sx={{ mb: 2 }}>
		<Typography className="mono-label" color="text.secondary" sx={{ mb: 0.75 }}>{title}</Typography>
		{entries.length === 0 ? <Typography variant="body2" color="text.disabled">{empty}</Typography> : <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, overflow: "hidden" }}><Table size="small"><TableBody>{entries.map(([name, value]) => <TableRow key={name}><TableCell sx={{ fontFamily: "var(--font-mono)", fontSize: "0.74rem", whiteSpace: "nowrap", verticalAlign: "top", width: "1%" }}>{name}</TableCell><TableCell sx={{ fontFamily: "var(--font-mono)", fontSize: "0.74rem", whiteSpace: "pre-wrap", wordBreak: "break-word", width: "99%" }}>{value}</TableCell></TableRow>)}</TableBody></Table></Box>}
	</Box>;
}

function RunDetailDialog({ runId, query, jobNames, onClose }) {
	const theme = useTheme();
	const [copied, setCopied] = useState(false);
	const run = query?.data;
	const mappingRun = useMemo(() => parseMappingRun(run), [run]);
	const responseText = useMemo(() => mappingRun ? "" : formatBody(run?.response_body), [mappingRun, run?.response_body]);
	const handleCopy = async () => {
		try {
			await navigator.clipboard.writeText(responseText || "");
			setCopied(true);
			window.setTimeout(() => setCopied(false), 1800);
		} catch {
			setCopied(false);
		}
	};
	return <Dialog open={runId !== null} onClose={onClose} maxWidth="md" fullWidth>
		<DialogTitle sx={{ display: "flex", alignItems: "center", gap: 1.25 }}>
			<Box sx={{ flex: 1, minWidth: 0 }}>
				<Typography variant="subtitle1">Run detail</Typography>
				{run ? <Typography variant="caption" color="text.secondary" className="mono">{jobNames[run.job_id] || run.job_id} · {run.method} · {formatExactTime(run.ran_at)}</Typography> : null}
			</Box>
			<IconButton onClick={onClose} aria-label="Close run detail"><Close /></IconButton>
		</DialogTitle>
		<Divider />
		<DialogContent dividers>
			{query?.isLoading ? <Box sx={{ py: 5, textAlign: "center" }}><CircularProgress size={26} /></Box> : query?.error ? <Alert severity="error">{getErrorMessage(query.error, "Could not load the run detail.")}</Alert> : !run ? <Typography variant="body2" color="text.secondary">This run is no longer available.</Typography> : <Box>
				<Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2, flexWrap: "wrap" }}>
					<Chip size="small" color={run.success ? "success" : "error"} icon={run.success ? <CheckCircle /> : <ErrorOutline />} label={run.status_code || "Error"} />
					<Typography variant="body2" className="mono">{formatDuration(run.duration_ms)}</Typography>
					<Typography variant="caption" color="text.secondary">{formatBytes(run.response_size)} response</Typography>
					<Tooltip title={`Local time · ${formatPreciseTime(run.ran_at)}`}><span><Typography variant="caption" color="text.secondary" className="mono">{formatRelative(run.ran_at)}</Typography></span></Tooltip>
					{run.response_body_truncated ? <Chip size="small" color="warning" label="Body truncated" /> : null}
				</Stack>
				<Typography variant="body2" className="mono" sx={{ mb: 0.5, wordBreak: "break-all" }}>{run.method} {run.url}</Typography>
				{run.error ? <Alert severity={run.success ? "info" : "error"} sx={{ my: 1.5 }}>{run.error}</Alert> : null}
				{mappingRun ? <MappingRunDetail mappingRun={mappingRun} theme={theme} /> : <>
					<Divider sx={{ my: 2 }} />
					<HeaderTable title="Request headers" headers={run.request_headers} empty="No request headers were captured for this run." />
					<HeaderTable title="Response headers" headers={run.response_headers} empty="No response headers were captured for this run." />
					<Box>
						<Stack direction="row" alignItems="center" sx={{ mb: 0.75 }}>
							<Typography className="mono-label" color="text.secondary" sx={{ flex: 1 }}>Response body</Typography>
							<Tooltip title={copied ? "Copied" : "Copy body"} arrow><span><Button size="small" disabled={!responseText} onClick={handleCopy} startIcon={copied ? <Done fontSize="small" /> : <ContentCopy fontSize="small" />}>Copy</Button></span></Tooltip>
						</Stack>
						{responseText ? <Box component="pre" sx={BODY_PRE_SX(theme)}>{responseText}</Box> : <Typography variant="body2" color="text.disabled">This run returned no body.</Typography>}
						{run.response_body_truncated ? <Typography variant="caption" color="warning.main">Only the first {formatBytes(run.response_size)} of the response were stored.</Typography> : null}
					</Box>
				</>}
			</Box>}
		</DialogContent>
		<DialogActions sx={{ px: 2.5, py: 1.5 }}>
			<Box sx={{ flex: 1 }} />
			<Button size="small" variant="contained" onClick={onClose}>Close</Button>
		</DialogActions>
	</Dialog>;
}


