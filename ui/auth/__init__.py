"""
ui/auth/

PyQt5 authentication UI screens for SanjINSIGHT.

Screens
-------
AdminSetupWizard        First-launch admin account creation (2-page wizard).
LoginScreen             Full-window login gate (replaces main content on startup).
SupervisorOverrideDialog  Compact overlay granting temporary engineer access at
                          an operator station.
UserManagementWidget    Admin-only widget embedded in SettingsTab for CRUD
                        on user accounts.
"""

from ui.auth.admin_setup_wizard        import AdminSetupWizard
from ui.auth.login_screen              import LoginScreen
from ui.auth.supervisor_override_dialog import SupervisorOverrideDialog
from ui.auth.user_management_widget    import UserManagementWidget

__all__ = [
    "AdminSetupWizard",
    "LoginScreen",
    "SupervisorOverrideDialog",
    "UserManagementWidget",
]
