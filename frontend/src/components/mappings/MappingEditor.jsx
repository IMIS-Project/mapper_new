import {
	closestCenter,
	DndContext,
	KeyboardSensor,
	PointerSensor,
	useSensor,
	useSensors,
} from "@dnd-kit/core";
import {
	arrayMove,
	SortableContext,
	sortableKeyboardCoordinates,
	verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import {
	Add,
	DeleteSweepOutlined,
	PauseCircleOutline,
	PlayCircleOutline,
	SwapVert,
} from "@mui/icons-material";
import {
	Box,
	Button,
	Checkbox,
	Chip,
	IconButton,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableRow,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useMemo, useState } from "react";

import MappingRow from "./MappingRow";
import { createMappingRow } from "./mappingModel";

const HEAD_CELL_SX = {
	fontFamily: "var(--font-mono)",
	fontSize: "0.6rem",
	fontWeight: 600,
	letterSpacing: "0.14em",
	textTransform: "uppercase",
	color: "text.secondary",
	py: 1,
	borderBottom: "1px solid",
	borderColor: "divider",
};

export default function MappingEditor({
	mappings = [],
	onChange,
	readOnly = false,
}) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";

	const [selectedIds, setSelectedIds] = useState(() => new Set());

	const sensors = useSensors(
		useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
		useSensor(KeyboardSensor, {
			coordinateGetter: sortableKeyboardCoordinates,
		}),
	);

	const ids = useMemo(() => mappings.map((row) => row.id), [mappings]);
	const enabledCount = mappings.filter((row) => row.enabled).length;
	const allSelected =
		mappings.length > 0 && selectedIds.size === mappings.length;
	const someSelected = selectedIds.size > 0 && !allSelected;

	const updateRow = (id, patch) =>
		onChange(
			mappings.map((row) => (row.id === id ? { ...row, ...patch } : row)),
		);

	const deleteRow = (id) => {
		onChange(mappings.filter((row) => row.id !== id));
		setSelectedIds((prev) => {
			const next = new Set(prev);
			next.delete(id);
			return next;
		});
	};

	const addRow = () => onChange([...mappings, createMappingRow()]);

	const toggleSelectAll = (checked) =>
		setSelectedIds(checked ? new Set(ids) : new Set());

	const toggleSelectRow = (id, checked) =>
		setSelectedIds((prev) => {
			const next = new Set(prev);
			if (checked) next.add(id);
			else next.delete(id);
			return next;
		});

	const bulkSetEnabled = (enabled) => {
		onChange(
			mappings.map((row) =>
				selectedIds.has(row.id) ? { ...row, enabled } : row,
			),
		);
		setSelectedIds(new Set());
	};

	const bulkDelete = () => {
		onChange(mappings.filter((row) => !selectedIds.has(row.id)));
		setSelectedIds(new Set());
	};

	const handleDragEnd = ({ active, over }) => {
		if (!over || active.id === over.id) return;
		const oldIndex = mappings.findIndex((row) => row.id === active.id);
		const newIndex = mappings.findIndex((row) => row.id === over.id);
		if (oldIndex < 0 || newIndex < 0) return;
		onChange(arrayMove(mappings, oldIndex, newIndex));
	};

	const renderTable = () => (
		<TableContainer
			sx={{
				border: "1px solid",
				borderColor: "divider",
				borderRadius: 2,
				maxHeight: 470,
				overflowX: "auto",
				"&::-webkit-scrollbar": { height: 8 },
			}}
		>
			<Table size="small" stickyHeader sx={{ minWidth: 940 }}>
				<TableHead>
					<TableRow
						sx={{
							"& th": {
								backgroundColor: isDark
									? alpha(theme.palette.background.default, 0.94)
									: alpha(theme.palette.background.default, 0.92),
								backdropFilter: "blur(6px)",
							},
						}}
					>
						{!readOnly && (
							<TableCell padding="checkbox" sx={{ ...HEAD_CELL_SX, width: 42 }}>
								<Checkbox
									size="small"
									checked={allSelected}
									indeterminate={someSelected}
									onChange={(event) => toggleSelectAll(event.target.checked)}
									slotProps={{
										input: { "aria-label": "Select all mapping rows" },
									}}
								/>
							</TableCell>
						)}
						<TableCell sx={{ ...HEAD_CELL_SX, width: 42, px: 0.5 }} />
						<TableCell sx={{ ...HEAD_CELL_SX, width: 40 }}>
							<Tooltip
								title="Order — drag rows to rearrange"
								arrow
								placement="top"
							>
								<SwapVert sx={{ fontSize: 14 }} />
							</Tooltip>
						</TableCell>
						<TableCell sx={HEAD_CELL_SX}>External field</TableCell>
						<TableCell sx={HEAD_CELL_SX}>Internal field</TableCell>
						<TableCell sx={HEAD_CELL_SX}>Type</TableCell>
						<TableCell sx={HEAD_CELL_SX}>Data type</TableCell>
						<TableCell align="center" sx={{ ...HEAD_CELL_SX, width: 74 }}>
							Enabled
						</TableCell>
						<TableCell align="right" sx={{ ...HEAD_CELL_SX, width: 52 }} />
					</TableRow>
				</TableHead>

				<TableBody>
					<SortableContext items={ids} strategy={verticalListSortingStrategy}>
						{mappings.map((mapping, index) => (
							<MappingRow
								key={mapping.id}
								mapping={mapping}
								index={index}
								readOnly={readOnly}
								showSelection={!readOnly}
								selected={selectedIds.has(mapping.id)}
								onSelectToggle={toggleSelectRow}
								onChange={updateRow}
								onDelete={deleteRow}
							/>
						))}
					</SortableContext>
				</TableBody>
			</Table>
		</TableContainer>
	);

	const renderEmpty = () => (
		<Box
			sx={{
				border: "1px dashed",
				borderColor: "divider",
				borderRadius: 2,
				py: 5,
				px: 3,
				textAlign: "center",
				backgroundColor: alpha(
					theme.palette.background.default,
					isDark ? 0.35 : 0.55,
				),
			}}
		>
			<Typography variant="body2" sx={{ color: "text.secondary", mb: 1.5 }}>
				No field mappings yet — add the first row to describe how an incoming
				field should land on the target request.
			</Typography>
		</Box>
	);

	return (
		<DndContext
			sensors={sensors}
			collisionDetection={closestCenter}
			onDragEnd={handleDragEnd}
		>
			{}
			<Box
				sx={{
					display: "flex",
					alignItems: "center",
					gap: 1,
					flexWrap: "wrap",
					mb: 1.5,
					minHeight: 34,
				}}
			>
				{selectedIds.size > 0 ? (
					<>
						<Typography
							variant="body2"
							sx={{ fontWeight: 600, fontSize: "0.78rem" }}
						>
							{selectedIds.size} selected
						</Typography>
						<Tooltip title="Enable selected" arrow>
							<IconButton
								size="small"
								onClick={() => bulkSetEnabled(true)}
								aria-label="Enable selected rows"
								sx={{ color: "success.main" }}
							>
								<PlayCircleOutline sx={{ fontSize: 19 }} />
							</IconButton>
						</Tooltip>
						<Tooltip title="Disable selected" arrow>
							<IconButton
								size="small"
								onClick={() => bulkSetEnabled(false)}
								aria-label="Disable selected rows"
								sx={{ color: "warning.main" }}
							>
								<PauseCircleOutline sx={{ fontSize: 19 }} />
							</IconButton>
						</Tooltip>
						<Tooltip title="Delete selected" arrow>
							<IconButton
								size="small"
								onClick={bulkDelete}
								aria-label="Delete selected rows"
								sx={{ color: "error.main" }}
							>
								<DeleteSweepOutlined sx={{ fontSize: 19 }} />
							</IconButton>
						</Tooltip>
					</>
				) : (
					!readOnly && (
						<Typography
							variant="caption"
							sx={{
								color: "text.disabled",
								display: "inline-flex",
								alignItems: "center",
								gap: 0.75,
							}}
						>
							<SwapVert sx={{ fontSize: 15 }} />
							Drag the handle to reorder — mappings apply top-down.
						</Typography>
					)
				)}

				<Box sx={{ flex: 1 }} />

				<Chip
					size="small"
					label={`${mappings.length} row${mappings.length === 1 ? "" : "s"}`}
					variant="outlined"
					sx={{ fontFamily: "var(--font-mono)", fontSize: "0.66rem" }}
				/>
				<Chip
					size="small"
					label={`${enabledCount} enabled`}
					sx={{
						fontFamily: "var(--font-mono)",
						fontSize: "0.66rem",
						color:
							enabledCount > 0 ? theme.palette.success.main : "text.disabled",
						backgroundColor: alpha(
							enabledCount > 0
								? theme.palette.success.main
								: theme.palette.text.disabled,
							isDark ? 0.16 : 0.09,
						),
						border: "1px solid",
						borderColor: alpha(
							enabledCount > 0
								? theme.palette.success.main
								: theme.palette.text.disabled,
							0.3,
						),
					}}
				/>
			</Box>

			{mappings.length === 0 ? renderEmpty() : renderTable()}

			{!readOnly && (
				<Button
					size="small"
					startIcon={<Add sx={{ fontSize: 18 }} />}
					onClick={addRow}
					sx={{
						mt: 1.5,
						px: 2,
						color: "text.secondary",
						border: "1px dashed",
						borderColor: "divider",
						borderRadius: 2,
						"&:hover": {
							color: "primary.main",
							borderColor: "primary.main",
							backgroundColor: alpha(theme.palette.primary.main, 0.05),
						},
					}}
				>
					Add mapping row
				</Button>
			)}
		</DndContext>
	);
}
