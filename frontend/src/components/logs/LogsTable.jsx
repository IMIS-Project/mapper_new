import { ContentCopy, ExpandMore, SearchOff } from "@mui/icons-material";
import {
	Box,
	Collapse,
	IconButton,
	LinearProgress,
	Skeleton,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableRow,
	TableSortLabel,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { Fragment, useMemo, useState } from "react";

import { useSnackbar } from "../../context/SnackbarContext";
import { formatLogTimestamp } from "../../services/localTime";
import MethodChip from "../common/MethodChip";
import StatusChip from "../common/StatusChip";
import LogDetail from "./LogDetail";

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

const shortId = (value) => {
	if (!value) return "—";
	const text = String(value);
	return text.length > 10 ? `${text.slice(0, 8)}…` : text;
};

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

const rowFailed = (row) => {
	const status = String(row.status || "").toLowerCase();
	if (status === "failed" || status === "error" || status === "failure")
		return true;
	if ((row.external_status_code ?? 0) >= 400) return true;
	return row.overall_status === false;
};

const rowRailColor = (row, theme) => {
	if (rowFailed(row)) return theme.palette.error.main;
	const status = String(row.status || "").toLowerCase();
	if (status === "success" || status === "ok" || row.overall_status === true) {
		return theme.palette.success.main;
	}
	return theme.palette.text.disabled;
};

function sortValue(row, key) {
	switch (key) {
		case "created_at":
			return new Date(row.created_at || 0).getTime() || 0;
		case "external_status_code":
			return row.external_status_code ?? -1;
		case "total_time_ms":
			return row.total_time_ms ?? -1;
		case "method":
		case "path":
		case "status":
		case "request_id":
			return String(row[key] || "").toLowerCase();
		default:
			return row[key];
	}
}

const COLUMNS = [
	{
		key: "created_at",
		label: "Timestamp",
		sortable: true,
		sx: { minWidth: 118 },
	},
	{ key: "request_id", label: "Request ID", sortable: true, hiddenBelow: "md" },
	{ key: "method", label: "Method", sortable: true, align: "center" },
	{ key: "path", label: "Path", sortable: true, hiddenBelow: "sm" },
	{ key: "status", label: "Status", sortable: true },
	{
		key: "external_status_code",
		label: "Code",
		sortable: true,
		align: "center",
		hiddenBelow: "sm",
	},
	{
		key: "total_time_ms",
		label: "Time",
		sortable: true,
		align: "right",
		hiddenBelow: "sm",
	},
	{
		key: "actions",
		label: "",
		sortable: false,
		align: "right",
		sx: { width: 52 },
	},
];

const hiddenSx = (threshold) =>
	threshold ? { display: { xs: "none", [threshold]: "table-cell" } } : {};

const SKELETON_ROWS = 6;

export default function LogsTable({
	logs = [],
	loading = false,
	refreshing = false,
	expandedId = null,
	onToggleExpand,
}) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const { showSnackbar } = useSnackbar();
	const [sort, setSort] = useState({ key: "created_at", dir: "desc" });

	const rows = useMemo(() => {
		const sorted = [...logs];
		sorted.sort((a, b) => {
			const left = sortValue(a, sort.key);
			const right = sortValue(b, sort.key);
			const cmp =
				typeof left === "number" && typeof right === "number"
					? left - right
					: String(left).localeCompare(String(right));
			return sort.dir === "asc" ? cmp : -cmp;
		});
		return sorted;
	}, [logs, sort]);

	const handleSort = (key) => {
		setSort((prev) =>
			prev.key === key
				? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
				: { key, dir: "asc" },
		);
	};

	const handleCopyId = async (event, value) => {
		event.stopPropagation();
		const ok = await copyText(String(value));
		showSnackbar(
			ok ? "Request ID copied" : "Copy failed — select the text manually.",
			ok ? "success" : "warning",
		);
	};

	const headCellSx = {
		py: 1.1,
		px: 1.5,
		borderBottom: "1px solid",
		borderColor: "divider",
		backgroundColor: alpha(theme.palette.background.paper, 0.94),
		backdropFilter: "blur(8px)",
		whiteSpace: "nowrap",
		"& .MuiTableSortLabel-root": {
			fontFamily: theme.typography.fontFamilyCode,
			fontSize: "0.64rem",
			letterSpacing: "0.09em",
			textTransform: "uppercase",
			color: "text.disabled",
			"&:hover": { color: "text.secondary" },
			"&.Mui-active": { color: "primary.main" },
		},
		"& .MuiTableSortLabel-icon": { fontSize: 15, opacity: 0.5 },
	};

	const bodyCellSx = {
		py: 1,
		px: 1.5,
		borderBottom: "1px solid",
		borderColor: alpha(theme.palette.divider, 0.7),
		verticalAlign: "middle",
	};

	return (
		<TableContainer sx={{ position: "relative", overflowX: "auto" }}>
			{refreshing ? (
				<LinearProgress
					sx={{
						position: "absolute",
						top: 0,
						left: 0,
						right: 0,
						height: 2,
						zIndex: 3,
					}}
				/>
			) : null}

			<Table size="small" stickyHeader sx={{ minWidth: { xs: 420, md: 860 } }}>
				<TableHead>
					<TableRow>
						{COLUMNS.map((column) => (
							<TableCell
								key={column.key}
								align={column.align || "left"}
								sortDirection={sort.key === column.key ? sort.dir : false}
								sx={{
									...headCellSx,
									...hiddenSx(column.hiddenBelow),
									...(column.sx || {}),
								}}
							>
								{column.sortable ? (
									<TableSortLabel
										active={sort.key === column.key}
										direction={sort.key === column.key ? sort.dir : "asc"}
										onClick={() => handleSort(column.key)}
									>
										{column.label}
									</TableSortLabel>
								) : (
									column.label
								)}
							</TableCell>
						))}
					</TableRow>
				</TableHead>

				<TableBody>
					{loading &&
						Array.from({ length: SKELETON_ROWS }).map((_, index) => (
							<TableRow key={`skeleton-${index}`}>
								<TableCell sx={bodyCellSx}>
									<Skeleton variant="text" width={104} height={20} />
									<Skeleton variant="text" width={64} height={14} />
								</TableCell>
								<TableCell sx={{ ...bodyCellSx, ...hiddenSx("md") }}>
									<Skeleton variant="text" width={72} height={18} />
								</TableCell>
								<TableCell align="center" sx={bodyCellSx}>
									<Skeleton variant="rounded" width={52} height={22} />
								</TableCell>
								<TableCell sx={{ ...bodyCellSx, ...hiddenSx("sm") }}>
									<Skeleton variant="text" width="82%" height={18} />
								</TableCell>
								<TableCell sx={bodyCellSx}>
									<Skeleton variant="rounded" width={78} height={22} />
								</TableCell>
								<TableCell
									align="center"
									sx={{ ...bodyCellSx, ...hiddenSx("sm") }}
								>
									<Skeleton
										variant="text"
										width={34}
										height={18}
										sx={{ mx: "auto" }}
									/>
								</TableCell>
								<TableCell
									align="right"
									sx={{ ...bodyCellSx, ...hiddenSx("sm") }}
								>
									<Skeleton
										variant="text"
										width={56}
										height={18}
										sx={{ ml: "auto" }}
									/>
								</TableCell>
								<TableCell align="right" sx={bodyCellSx}>
									<Skeleton
										variant="circular"
										width={22}
										height={22}
										sx={{ ml: "auto" }}
									/>
								</TableCell>
							</TableRow>
						))}

					{!loading && rows.length === 0 && (
						<TableRow>
							<TableCell
								colSpan={COLUMNS.length}
								sx={{ borderBottom: 0, py: 0 }}
							>
								<Box
									sx={{
										display: "flex",
										flexDirection: "column",
										alignItems: "center",
										gap: 1.25,
										py: 7,
										px: 2,
										textAlign: "center",
									}}
								>
									<Box
										sx={{
											width: 52,
											height: 52,
											borderRadius: "16px",
											display: "flex",
											alignItems: "center",
											justifyContent: "center",
											color: "text.disabled",
											backgroundColor: alpha(
												theme.palette.text.primary,
												isDark ? 0.05 : 0.03,
											),
											border: "1px dashed",
											borderColor: "divider",
										}}
									>
										<SearchOff sx={{ fontSize: 24 }} />
									</Box>
									<Typography variant="subtitle2">
										No call logs found
									</Typography>
									<Typography
										variant="body2"
										sx={{ color: "text.secondary", maxWidth: 380 }}
									>
										Nothing matches the current filters. Adjust or clear them,
										or wait for traffic to flow through the gateway.
									</Typography>
								</Box>
							</TableCell>
						</TableRow>
					)}

					{!loading &&
						rows.map((row) => {
							const expanded = expandedId === row.id;
							const stamp = formatLogTimestamp(row.created_at);
							const railColor = rowRailColor(row, theme);

							return (
								<Fragment key={row.id}>
									<TableRow
										hover
										onClick={() => onToggleExpand?.(row.id)}
										sx={{
											cursor: "pointer",
											transition: "background-color 0.15s ease",
											backgroundColor: expanded
												? alpha(
														theme.palette.primary.main,
														isDark ? 0.09 : 0.045,
													)
												: "transparent",
											"& > td:first-of-type": {
												boxShadow: `inset 3px 0 0 0 ${expanded ? theme.palette.primary.main : railColor}`,
											},
										}}
									>
										<TableCell sx={bodyCellSx}>
											<Typography
												sx={{
													fontFamily: theme.typography.fontFamilyCode,
													fontSize: "0.72rem",
													fontWeight: 600,
													lineHeight: 1.35,
													color: "text.primary",
												}}
											>
												{stamp.time}
											</Typography>
											<Typography
												sx={{
													fontFamily: theme.typography.fontFamilyCode,
													fontSize: "0.62rem",
													lineHeight: 1.35,
													color: "text.disabled",
												}}
											>
												{stamp.date}
											</Typography>
										</TableCell>

										<TableCell sx={{ ...bodyCellSx, ...hiddenSx("md") }}>
											<Box
												sx={{
													display: "flex",
													alignItems: "center",
													gap: 0.25,
												}}
											>
												<Tooltip title={String(row.request_id || "")} arrow>
													<Typography
														sx={{
															fontFamily: theme.typography.fontFamilyCode,
															fontSize: "0.72rem",
															color: "text.secondary",
														}}
													>
														{shortId(row.request_id)}
													</Typography>
												</Tooltip>
												<Tooltip title="Copy request ID" arrow>
													<IconButton
														size="small"
														aria-label="Copy request ID"
														onClick={(event) =>
															handleCopyId(event, row.request_id)
														}
														sx={{
															color: "text.disabled",
															"&:hover": { color: "primary.main" },
														}}
													>
														<ContentCopy sx={{ fontSize: 13 }} />
													</IconButton>
												</Tooltip>
											</Box>
										</TableCell>

										<TableCell align="center" sx={bodyCellSx}>
											<MethodChip method={row.method} />
										</TableCell>

										<TableCell sx={{ ...bodyCellSx, ...hiddenSx("sm") }}>
											<Tooltip
												title={row.path || ""}
												arrow
												placement="top-start"
											>
												<Typography
													sx={{
														fontFamily: theme.typography.fontFamilyCode,
														fontSize: "0.72rem",
														color: "text.primary",
														overflow: "hidden",
														textOverflow: "ellipsis",
														whiteSpace: "nowrap",
														maxWidth: { sm: 200, lg: 320 },
													}}
												>
													{row.path || "—"}
												</Typography>
											</Tooltip>
										</TableCell>

										<TableCell sx={bodyCellSx}>
											<StatusChip
												status={
													row.status ||
													(row.overall_status ? "success" : "failed")
												}
											/>
										</TableCell>

										<TableCell
											align="center"
											sx={{ ...bodyCellSx, ...hiddenSx("sm") }}
										>
											<Typography
												component="span"
												sx={{
													fontFamily: theme.typography.fontFamilyCode,
													fontSize: "0.74rem",
													fontWeight: 700,
													color: codeColor(row.external_status_code, theme),
												}}
											>
												{row.external_status_code ?? "—"}
											</Typography>
										</TableCell>

										<TableCell
											align="right"
											sx={{ ...bodyCellSx, ...hiddenSx("sm") }}
										>
											<Typography
												component="span"
												sx={{
													fontFamily: theme.typography.fontFamilyCode,
													fontSize: "0.72rem",
													fontWeight: 600,
													color: timeColor(row.total_time_ms, theme),
												}}
											>
												{row.total_time_ms === null ||
												row.total_time_ms === undefined
													? "—"
													: `${Number(row.total_time_ms).toLocaleString("en-US")} ms`}
											</Typography>
										</TableCell>

										<TableCell align="right" sx={{ ...bodyCellSx, pr: 1 }}>
											<Tooltip
												title={
													expanded ? "Collapse detail" : "View full detail"
												}
												arrow
											>
												<IconButton
													size="small"
													aria-label={
														expanded ? "Collapse detail" : "View full detail"
													}
													aria-expanded={expanded}
													onClick={(event) => {
														event.stopPropagation();
														onToggleExpand?.(row.id);
													}}
													sx={{
														color: expanded ? "primary.main" : "text.disabled",
														"&:hover": { color: "primary.main" },
													}}
												>
													<ExpandMore
														sx={{
															fontSize: 18,
															transition: "transform 0.24s ease",
															transform: expanded ? "rotate(180deg)" : "none",
														}}
													/>
												</IconButton>
											</Tooltip>
										</TableCell>
									</TableRow>

									{expanded && (
										<TableRow>
											<TableCell
												colSpan={COLUMNS.length}
												sx={{
													p: 0,
													borderBottom: "1px solid",
													borderColor: "divider",
												}}
											>
												<Collapse in appear timeout={240}>
													<LogDetail logId={row.id} />
												</Collapse>
											</TableCell>
										</TableRow>
									)}
								</Fragment>
							);
						})}
				</TableBody>
			</Table>
		</TableContainer>
	);
}
