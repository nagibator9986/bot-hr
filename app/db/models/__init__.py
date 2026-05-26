"""Импорт всех моделей в одном месте, чтобы Alembic видел метаданные."""

from app.db.models.candidate import Candidate
from app.db.models.conversation import ConversationMessage
from app.db.models.employer import Employer
from app.db.models.interview import Interview
from app.db.models.match import Match
from app.db.models.payment import Payment
from app.db.models.referral import Referral, ReferralBalance, WithdrawalRequest
from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.db.models.vacancy import Vacancy

__all__ = [
    "Candidate",
    "ConversationMessage",
    "Employer",
    "Interview",
    "Match",
    "Payment",
    "Referral",
    "ReferralBalance",
    "Subscription",
    "User",
    "Vacancy",
    "WithdrawalRequest",
]
