"""Modal dialogs for the Moment GUI."""

from src.gui.dialogs.add_flag import AddFlagDialog
from src.gui.dialogs.crop import CropBetweenFlagsDialog
from src.gui.dialogs.duplicate_clip import DuplicateClipDialog
from src.gui.dialogs.import_image import ImportImageDialog
from src.gui.dialogs.import_video import ImportVideoDialog
from src.gui.dialogs.insert_clip import InsertClipDialog
from src.gui.dialogs.new_project import NewProjectDialog
from src.gui.dialogs.voiceover_mode import VoiceoverModeDialog, configure_voiceover_default

__all__ = [
    "AddFlagDialog",
    "CropBetweenFlagsDialog",
    "DuplicateClipDialog",
    "ImportImageDialog",
    "ImportVideoDialog",
    "InsertClipDialog",
    "NewProjectDialog",
    "VoiceoverModeDialog",
    "configure_voiceover_default",
]
