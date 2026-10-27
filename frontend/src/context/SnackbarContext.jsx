import { Alert, Slide, Snackbar } from "@mui/material";
import {
	createContext,
	useCallback,
	useContext,
	useMemo,
	useState,
} from "react";

const SnackbarContext = createContext(null);

function sanitizeSnackbarMessage(msg) {
	if (!msg) return "";
	if (typeof msg === "string") {
		const trimmed = msg.trim();
		if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
			try {
				const parsed = JSON.parse(trimmed);
				return sanitizeSnackbarMessage(parsed);
			} catch {}
		}
		return trimmed;
	}
	if (typeof msg === "object") {
		if (typeof msg.message === "string") return sanitizeSnackbarMessage(msg.message);
		if (typeof msg.msg === "string") return sanitizeSnackbarMessage(msg.msg);
		if (typeof msg.error === "string") return sanitizeSnackbarMessage(msg.error);
		if (msg.detail !== undefined) return sanitizeSnackbarMessage(msg.detail);
	}
	return String(msg);
}

export function SnackbarProvider({ children }) {
	const [state, setState] = useState({
		open: false,
		message: "",
		severity: "info",
		key: 0,
	});

	const showSnackbar = useCallback((message, severity = "info") => {
		const cleanMessage = sanitizeSnackbarMessage(message);
		setState((prev) => ({
			open: true,
			message: cleanMessage,
			severity,

			key: prev.key + 1,
		}));
	}, []);

	const hideSnackbar = useCallback((_event, reason) => {
		if (reason === "clickaway") return;
		setState((prev) => ({ ...prev, open: false }));
	}, []);

	const value = useMemo(
		() => ({ showSnackbar, hideSnackbar }),
		[showSnackbar, hideSnackbar],
	);

	return (
		<SnackbarContext.Provider value={value}>
			{children}
			<Snackbar
				key={state.key}
				open={state.open}
				autoHideDuration={4200}
				onClose={hideSnackbar}
				anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
				slots={{ transition: Slide }}
				slotProps={{ transition: { direction: "up" } }}
			>
				<Alert
					onClose={hideSnackbar}
					severity={state.severity}
					variant="filled"
					sx={{ minWidth: 280, alignItems: "center", boxShadow: 6 }}
				>
					{state.message}
				</Alert>
			</Snackbar>
		</SnackbarContext.Provider>
	);
}

export function useSnackbar() {
	const context = useContext(SnackbarContext);
	if (!context) {
		throw new Error("useSnackbar must be used within a SnackbarProvider");
	}
	return context;
}

export default SnackbarContext;
