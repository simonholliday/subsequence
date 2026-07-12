(remove-hook 'python-mode-hook 'blacken-mode)

(require 'ruff-format)
(add-hook 'python-mode-hook 'ruff-format-on-save-mode)
