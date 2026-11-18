// What TypeScript cannot see in Kiboto's plain-JavaScript frontend by itself (ARC-31, 18 Nov 2026).
// The frontend is not TypeScript; this file only feeds the type check (npm run lint:types).
export {};

declare global {
  // Functions and objects modules put on window for each other and for markup handlers. Typed
  // loosely on purpose: the list says which exist; a misspelt one is still an error.
  interface Window {
    __forceAiStreamingTest: any;
    __kibotoClientLogger: any;
    __updateManagementTelemetry: any;
    __VITEST__: any;
    __zettActiveFmDrag: any;
    _activeDragPayload: any;
    _containersManagerInitialized: any;
    _fmInitialized: any;
    _fmRoots: any;
    _jsdom: any;
    _personalizationInitialized: any;
    _vmConsoleGlobalCaptureBound: any;
    _vmJoinDismissRegistered: any;
    _vmManagerInitialized: any;
    activateScreensaver: any;
    alignDesktopGrid: any;
    announceA11y: any;
    applyDashboardLayout: any;
    applyDockSettings: any;
    applyGlassSettings: any;
    applyScreensaverSettings: any;
    applyStats: any;
    applyWallpaperReadability: any;
    askKibAbout: any;
    attachGlassTimePicker: any;
    bringToFront: any;
    closeAllFileManagerWindows: any;
    closeCalendarModal: any;
    closeDeletePresetModal: any;
    closeDrawer: any;
    closeEventDetailModal: any;
    closeFilePreviewModal: any;
    closeGlassTimePicker: any;
    closeHttpsGuideModal: any;
    closePersonalizationWindow: any;
    closeSavePresetModal: any;
    closeSmartModal: any;
    closeTimezoneModal: any;
    closeUpsDrawer: any;
    deactivateScreensaver: any;
    deployComposeStackSnippet: any;
    DockManager: any;
    executeContextAction: any;
    exportCalendarIcs: any;
    fetchAndRenderSecurityPosture: any;
    fetchCalendarEvents: any;
    fetchCalendarFeeds: any;
    fetchDashboardLayout: any;
    formatDisplayTime: any;
    formatTime24: any;
    getActiveFmInstance: any;
    getActiveWindowElement: any;
    getCurrentWorkspace: any;
    getDockSettings: any;
    getScreensaverSettings: any;
    getWidgetDisplayName: any;
    getWidgetKeyFromElement: any;
    handleSecurityAdvisorClick: any;
    hideDesktopContextMenu: any;
    hideWidgetContextMenu: any;
    initCalendarView: any;
    initDockSettingsControls: any;
    initGlassTimePickers: any;
    initParabolicDockMagnification: any;
    initScreensaverSettingsControls: any;
    initScreensaverSystem: any;
    initTimezoneControls: any;
    initUpsDrawerControls: any;
    initWorkspaceSwitcher: any;
    isEventChecked: any;
    loadSavedWindowBounds: any;
    loadWallpapers: any;
    lockDesktop: any;
    lockDesktopScreen: any;
    makeDesktopIconDraggable: any;
    markEventChecked: any;
    mountTabsInDrawer: any;
    navigateToPath: any;
    openAddDesktopShortcutModal: any;
    openCalendarModal: any;
    openConsoleWindow: any;
    openContainerInspector: any;
    openContainersManager: any;
    openContainersWindow: any;
    openDeletePresetModal: any;
    openDrawer: any;
    openEventDetailModal: any;
    openFileManager: any;
    openFilePreviewModal: any;
    openFolderBrowser: any;
    openGettingStarted: any;
    openGlassTimePicker: any;
    openHttpsGuideModal: any;
    openJobsCentre: any;
    openManagementSection: any;
    openManagementWindow: any;
    openNewCloudRemoteModal: any;
    openNewFileManagerWindow: any;
    openPersonalizationWindow: any;
    openRecycleBin: any;
    openSavePresetModal: any;
    openSetupWizard: any;
    openShareLinkModal: any;
    openSpotlight: any;
    openTimezoneModal: any;
    openUpsDrawer: any;
    openVmConnectModal: any;
    openVmConsoleSeparateWindow: any;
    openVmEditModal: any;
    openVmManager: any;
    openVmSnapshotsModal: any;
    openWidgetSettings: any;
    parseTime24: any;
    refreshDesktopIconPositions: any;
    removeWidget: any;
    renderContainersWindowTable: any;
    renderNotificationCenter: any;
    resetCheckedEventsState: any;
    restoreHardwareTabsToManagement: any;
    restoreOpenWindowsState: any;
    restoreWindowSnap: any;
    saveOpenWindowsState: any;
    saveUpsConfigFromDrawer: any;
    saveWidgetConfig: any;
    saveWindowBounds: any;
    selectWallpaper: any;
    setUpsConfigLoaded: any;
    setWallpaper: any;
    setWindowRestorationComplete: any;
    showDesktopContextMenu: any;
    showWidgetContextMenu: any;
    sortDesktopIcons: any;
    state: any;
    switchLcdPage: any;
    switchWorkspace: any;
    syncDesktopTwinPreview: any;
    toggleConsoleMaximize: any;
    toggleNotificationCenter: any;
    transferCenter: any;
    updateLcdPages: any;
    updateUpsConnCardState: any;
    updateUpsPolicySliders: any;
    updateUpsPolicySummary: any;
    VITEST: any;
  }

  // State the frontend keeps on its own elements (an underscore marks each one as Kiboto's)
  interface HTMLElement {
    _activeAppId?: any;
    _activeMode?: any;
    _anchor?: any;
    _clickDelegated?: any;
    _close?: any;
    _data?: any;
    _eventData?: any;
    _fadeTimeout?: any;
    _hasDelegatedClicks?: any;
    _hasMiniDrag?: any;
    _hasMiniDrop?: any;
    _isDeploying?: any;
    _lastRenderedSignature?: any;
    _setConsoleMode?: any;
    _snapAssistBound?: any;
    _targetPreset?: any;
    _unbindTrap?: any;
    _userClosing?: any;
    _vmId?: any;
    _vmName?: any;
  }

  // A string selector in this frontend finds HTML elements: typed so, as TypeScript's own
  // tag-name lookups are (querySelector('svg') and the like keep their exact types).
  interface ParentNode {
    querySelector<E extends Element = HTMLElement>(selectors: string): E | null;
    querySelectorAll<E extends Element = HTMLElement>(selectors: string): NodeListOf<E>;
  }
  interface Element {
    closest<E extends Element = HTMLElement>(selectors: string): E | null;
  }
}
