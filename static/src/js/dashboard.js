/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class MigrateDashboard extends Component {
    static template = "navigare_migrate.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.rpc = useService("rpc");

        this.state = useState({
            operationsToday: 0,
            successRate: 0,
            totalProcessed: 0,
            activeSchedules: 0,
            recentOperations: [],
            dailyStats: [],
            loading: true,
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        try {
            const data = await this.rpc("/navigare_migrate/dashboard_data", {});
            this.state.operationsToday = data.operations_today || 0;
            this.state.successRate = data.success_rate || 0;
            this.state.totalProcessed = data.total_processed || 0;
            this.state.activeSchedules = data.active_schedules || 0;
            this.state.recentOperations = data.recent_operations || [];
            this.state.dailyStats = data.daily_stats || [];
        } catch (error) {
            console.error("Failed to load dashboard data:", error);
        } finally {
            this.state.loading = false;
        }
    }

    openImportWizard() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Import Data",
            res_model: "migrate.import.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    }

    openExportWizard() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Export Data",
            res_model: "migrate.export.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    }

    openOperation(operationId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Operation",
            res_model: "migrate.operation",
            res_id: operationId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    getStateBadgeClass(state) {
        const map = {
            done: "text-bg-success",
            error: "text-bg-danger",
            partial: "text-bg-warning",
            running: "text-bg-info",
            dry_run: "text-bg-secondary",
            draft: "text-bg-light",
            cancelled: "text-bg-light",
        };
        return map[state] || "text-bg-secondary";
    }

    formatDuration(seconds) {
        if (!seconds) return "-";
        if (seconds < 60) return `${Math.round(seconds)}s`;
        const mins = Math.floor(seconds / 60);
        const secs = Math.round(seconds % 60);
        return `${mins}m ${secs}s`;
    }

    formatNumber(num) {
        if (num === undefined || num === null) return "0";
        return num.toLocaleString();
    }
}

registry.category("actions").add("navigare_migrate.Dashboard", MigrateDashboard);
