import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { DeleteOutline, DragIndicator } from "@mui/icons-material";
import {
	Checkbox,
	IconButton,
	MenuItem,
	Select,
	Switch,
	TableCell,
	TableRow,
	TextField,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, lighten, useTheme } from "@mui/material/styles";

import {
	DATA_TYPE_OPTIONS,
	PARAM_TYPE_COLORS,
	PARAM_TYPE_OPTIONS,
} from "./mappingModel";

export default function MappingRow({
	mapping,
	index,
	readOnly = false,
	showSelection = false,
	selected = false,
	onSelectToggle,
	onChange,
	onDelete,
}) {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;
	const isDark = theme.palette.mode === "dark";

	const paramAccent = (type) => {
		const base = PARAM_TYPE_COLORS[type];
		if (!base) return undefined;
		return isDark ? lighten(base, 0.35) : base;
	};

	const {
		attributes,
		listeners,
		setNodeRef,
		transform,
		transition,
		isDragging,
	} = useSortable({
		id: mapping.id,
		disabled: readOnly,
	});

	const style = {
		transform: CSS.Transform.toString(transform),
		transition,
	};

	const fieldSx = {
		"& .MuiInputBase-input": {
			fontFamily: codeFont,
			fontSize: "0.78rem",
			py: 0.9,
		},
		"& .MuiInputBase-input::placeholder": {
			fontFamily: codeFont,
			fontSize: "0.72rem",
			opacity: 0.6,
		},
	};

	const selectSx = {
		fontFamily: codeFont,
		fontSize: "0.74rem",
		fontWeight: 600,
		"& .MuiSelect-select": { py: 0.95 },
	};

	return (
		<TableRow
			ref={setNodeRef}
			hover
			style={style}
			sx={{
				opacity: mapping.enabled ? 1 : 0.55,
				transition: `${transition ? `${transition}, ` : ""}opacity 0.18s ease`,
				...(selected && {
					backgroundColor: alpha(
						theme.palette.primary.main,
						isDark ? 0.1 : 0.05,
					),
				}),
				...(isDragging && {
					position: "relative",
					zIndex: 3,
					opacity: 0.9,
					backgroundColor: alpha(
						theme.palette.primary.main,
						isDark ? 0.16 : 0.08,
					),
				}),
				"&:hover": {
					backgroundColor: alpha(
						theme.palette.primary.main,
						isDark ? 0.07 : 0.035,
					),
				},
			}}
		>
			{showSelection && (
				<TableCell padding="checkbox" sx={{ width: 42 }}>
					<Checkbox
						size="small"
						checked={selected}
						onChange={(event) =>
							onSelectToggle?.(mapping.id, event.target.checked)
						}
						slotProps={{
							input: { "aria-label": `Select mapping row ${index + 1}` },
						}}
					/>
				</TableCell>
			)}

			<TableCell sx={{ width: 42, px: 0.5 }}>
				{!readOnly && (
					<Tooltip title="Drag to reorder" arrow>
						<IconButton
							size="small"
							{...attributes}
							{...listeners}
							aria-label={`Reorder mapping row ${index + 1}`}
							sx={{
								cursor: "grab",
								touchAction: "none",
								color: "text.disabled",
								"&:hover": { color: "text.secondary" },
								"&:active": { cursor: "grabbing" },
							}}
						>
							<DragIndicator sx={{ fontSize: 18 }} />
						</IconButton>
					</Tooltip>
				)}
			</TableCell>

			<TableCell sx={{ width: 40, pr: 0.5 }}>
				<Typography
					variant="caption"
					sx={{
						fontFamily: codeFont,
						color: "text.disabled",
						fontSize: "0.68rem",
					}}
				>
					{String(index + 1).padStart(2, "0")}
				</Typography>
			</TableCell>

			<TableCell sx={{ minWidth: 190 }}>
				<TextField
					fullWidth
					size="small"
					placeholder="external.field"
					value={mapping.sourceField}
					onChange={(event) =>
						onChange(mapping.id, { sourceField: event.target.value })
					}
					disabled={readOnly}
					sx={fieldSx}
					slotProps={{
						htmlInput: { "aria-label": `External field, row ${index + 1}` },
					}}
				/>
			</TableCell>

			<TableCell sx={{ minWidth: 190 }}>
				<TextField
					fullWidth
					size="small"
					placeholder="internal.field"
					value={mapping.targetField}
					onChange={(event) =>
						onChange(mapping.id, { targetField: event.target.value })
					}
					disabled={readOnly}
					sx={fieldSx}
					slotProps={{
						htmlInput: { "aria-label": `Internal field, row ${index + 1}` },
					}}
				/>
			</TableCell>

			<TableCell sx={{ minWidth: 128 }}>
				<Select
					fullWidth
					size="small"
					value={mapping.parameterType}
					onChange={(event) =>
						onChange(mapping.id, { parameterType: event.target.value })
					}
					disabled={readOnly}
					aria-label={`Parameter type, row ${index + 1}`}
					sx={{
						...selectSx,
						color: paramAccent(mapping.parameterType) || "text.primary",
					}}
				>
					{PARAM_TYPE_OPTIONS.map((option) => (
						<MenuItem
							key={option}
							value={option}
							sx={{
								fontFamily: codeFont,
								fontSize: "0.76rem",
								fontWeight: 600,
								color: paramAccent(option),
							}}
						>
							{option}
						</MenuItem>
					))}
				</Select>
			</TableCell>

			<TableCell sx={{ minWidth: 138 }}>
				<Select
					fullWidth
					size="small"
					value={mapping.dataType}
					onChange={(event) =>
						onChange(mapping.id, { dataType: event.target.value })
					}
					disabled={readOnly}
					aria-label={`Data type, row ${index + 1}`}
					sx={{ ...selectSx, color: "text.secondary", fontWeight: 500 }}
				>
					{DATA_TYPE_OPTIONS.map((option) => (
						<MenuItem
							key={option}
							value={option}
							sx={{ fontFamily: codeFont, fontSize: "0.76rem" }}
						>
							{option}
						</MenuItem>
					))}
				</Select>
			</TableCell>

			<TableCell align="center" sx={{ width: 74 }}>
				<Tooltip
					title={
						mapping.enabled ? "Disable this mapping" : "Enable this mapping"
					}
					arrow
				>
					<Switch
						size="small"
						checked={Boolean(mapping.enabled)}
						onChange={(event) =>
							onChange(mapping.id, { enabled: event.target.checked })
						}
						disabled={readOnly}
						slotProps={{
							input: { "aria-label": `Enable mapping row ${index + 1}` },
						}}
					/>
				</Tooltip>
			</TableCell>

			<TableCell align="right" sx={{ width: 52 }}>
				{!readOnly && (
					<Tooltip title="Remove row" arrow>
						<IconButton
							size="small"
							onClick={() => onDelete(mapping.id)}
							aria-label={`Remove mapping row ${index + 1}`}
							sx={{
								color: "text.disabled",
								"&:hover": { color: "error.main" },
							}}
						>
							<DeleteOutline sx={{ fontSize: 18 }} />
						</IconButton>
					</Tooltip>
				)}
			</TableCell>
		</TableRow>
	);
}
