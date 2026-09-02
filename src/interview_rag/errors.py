class InterviewRAGError(Exception):
    """利用者に表示できる、想定内のアプリケーションエラー。"""


class ConfigurationError(InterviewRAGError):
    """設定が不足または不正。"""


class DataValidationError(InterviewRAGError):
    """保存データまたはLLM出力が不正。"""


class IndexMismatchError(InterviewRAGError):
    """Knowledgeと索引の整合性が取れない。"""
