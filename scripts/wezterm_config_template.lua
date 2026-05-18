-- ClawSeat WezTerm Configuration
local wezterm = require 'wezterm'
local config = wezterm.config_builder()

-- Window settings
config.window_decorations = "RESIZE"
config.window_padding = { left = 4, right = 4, top = 4, bottom = 4 }
config.initial_cols = 120
config.initial_rows = 40

-- Font
config.font = wezterm.font('JetBrains Mono', { weight = 'Regular' })
config.font_size = 12.0
config.line_height = 1.2

-- Color scheme
config.color_scheme = 'Dracula'

-- Tab bar
config.enable_tab_bar = true
config.use_fancy_tab_bar = true
config.tab_bar_at_bottom = false
config.hide_tab_bar_if_only_one_tab = false

-- Pane settings
config.pane_focus_follows_mouse = true

-- Scrollback
config.scrollback_lines = 10000

-- Key bindings for pane management
config.keys = {
  -- Pane splitting
  { key = 'd', mods = 'CTRL|SHIFT', action = wezterm.action.SplitHorizontal { domain = 'CurrentPaneDomain' } },
  { key = 'd', mods = 'CTRL|SHIFT|ALT', action = wezterm.action.SplitVertical { domain = 'CurrentPaneDomain' } },
  -- Pane navigation
  { key = 'h', mods = 'CTRL|SHIFT', action = wezterm.action.ActivatePaneDirection 'Left' },
  { key = 'j', mods = 'CTRL|SHIFT', action = wezterm.action.ActivatePaneDirection 'Down' },
  { key = 'k', mods = 'CTRL|SHIFT', action = wezterm.action.ActivatePaneDirection 'Up' },
  { key = 'l', mods = 'CTRL|SHIFT', action = wezterm.action.ActivatePaneDirection 'Right' },
  -- Pane resizing
  { key = 'LeftArrow', mods = 'CTRL|SHIFT|ALT', action = wezterm.action.AdjustPaneSize { 'Left', 3 } },
  { key = 'RightArrow', mods = 'CTRL|SHIFT|ALT', action = wezterm.action.AdjustPaneSize { 'Right', 3 } },
  { key = 'UpArrow', mods = 'CTRL|SHIFT|ALT', action = wezterm.action.AdjustPaneSize { 'Up', 3 } },
  { key = 'DownArrow', mods = 'CTRL|SHIFT|ALT', action = wezterm.action.AdjustPaneSize { 'Down', 3 } },
  -- Tab navigation
  { key = 't', mods = 'CTRL|SHIFT', action = wezterm.action.SpawnTab 'CurrentPaneDomain' },
  { key = 'w', mods = 'CTRL|SHIFT', action = wezterm.action.CloseCurrentTab { confirm = true } },
  { key = '1', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTab(0) },
  { key = '2', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTab(1) },
  { key = '3', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTab(2) },
  { key = '4', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTab(3) },
  { key = '5', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTab(4) },
  { key = '6', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTab(5) },
  { key = '7', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTab(6) },
  { key = '8', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTab(7) },
}

-- Mouse bindings
config.mouse_bindings = {
  {
    event = { Down = { streak = 1, button = 'Right' } },
    mods = 'NONE',
    action = wezterm.action.PasteFrom 'Clipboard',
  },
}

-- Default shell
config.default_prog = { 'powershell.exe', '-NoLogo' }

return config
