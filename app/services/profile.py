"""Рендеринг карточек кандидата и вакансии (caption для фото-сообщений)."""

from __future__ import annotations

from app.core.constants import HORECA_POSITIONS, Schedule
from app.db.models.candidate import Candidate
from app.db.models.vacancy import Vacancy
from app.locales import RU
from app.utils.text import mask_address, mask_name

_SCHEDULE_LABELS: dict[str, str] = {
    Schedule.SHIFT.value: RU["schedule_shift"],
    Schedule.FULL_TIME.value: RU["schedule_full_time"],
    Schedule.PART_TIME.value: RU["schedule_part_time"],
    Schedule.FLEXIBLE.value: RU["schedule_flexible"],
}


def schedule_label(value: str) -> str:
    return _SCHEDULE_LABELS.get(value, value)


def position_label(normalized: str, fallback: str) -> str:
    """Человекочитаемое название должности из канонич. формы."""
    return HORECA_POSITIONS.get(normalized, fallback)


def fmt_money(amount: int | float) -> str:
    """450000 → '450 000'."""
    return f"{int(amount):,}".replace(",", " ")


def fmt_salary_range(vacancy: Vacancy) -> str:
    """Вилка зарплаты вакансии: '300 000 – 400 000' либо '300 000', если границы равны."""
    lo, hi = int(vacancy.salary_min), int(vacancy.salary_max)
    if lo == hi:
        return fmt_money(lo)
    return f"{fmt_money(lo)} – {fmt_money(hi)}"


def requirements_text(requirements: object) -> str:
    """Человекочитаемые требования вакансии.

    Приоритет — AI-сводка (`summary`), иначе исходный текст (`raw`). Навыки,
    извлечённые AI, добавляются отдельной строкой.
    """
    if not isinstance(requirements, dict):
        return "—"
    summary = str(requirements.get("summary", "") or "").strip()
    raw = str(requirements.get("raw", "") or "").strip()
    base = summary or raw or "—"
    skills = requirements.get("skills")
    if isinstance(skills, list) and skills:
        base += "\n🔑 " + ", ".join(str(s) for s in skills[:7])
    return base


def render_candidate_card(candidate: Candidate, *, preview: bool = False) -> str:
    """Caption для фото-карточки кандидата (свайп-просмотр работодателя)."""
    about = f"\n💬 {candidate.about}" if candidate.about else ""
    name = mask_name(candidate.name) if preview else candidate.name
    contact = RU["preview_contact_hidden"] if preview else candidate.contact
    preferred_area = (
        f"\n📍 Предпочтительный район: {candidate.preferred_area}"
        if candidate.preferred_area
        else ""
    )
    return RU["card_candidate"].format(
        name=name,
        age=candidate.age,
        city=candidate.city,
        position=position_label(candidate.position_normalized, candidate.desired_position),
        experience=candidate.experience_years,
        schedule=schedule_label(candidate.schedule),
        salary=fmt_money(candidate.expected_salary),
        contact=contact,
        preferred_area=preferred_area,
        about=about,
    )


def render_vacancy_card(vacancy: Vacancy, *, preview: bool = False) -> str:
    """Caption для карточки вакансии (свайп-просмотр кандидата)."""
    company = vacancy.employer.company_name if vacancy.employer else "—"
    address = vacancy.address
    if preview:
        company = "***"
        address = mask_address(vacancy.address)
    elif vacancy.employer is not None and vacancy.employer.is_verified:
        company = f"{company}  {RU['verified_badge']}"
    requirements = requirements_text(vacancy.requirements)
    conditions = f"\n✅ Условия: {vacancy.conditions}" if vacancy.conditions else ""
    return RU["card_vacancy"].format(
        company=company,
        position=position_label(vacancy.position_normalized, vacancy.position),
        city=vacancy.city,
        address=address,
        schedule=schedule_label(vacancy.schedule),
        salary=fmt_salary_range(vacancy),
        requirements=requirements,
        conditions=conditions,
    )


def render_candidate_summary(candidate: Candidate) -> str:
    """Полная сводка анкеты для экрана подтверждения / «Моя анкета»."""
    lines = [
        "👤 <b>Моя анкета</b>\n",
        f"<b>Имя:</b> {candidate.name}",
        f"<b>Возраст:</b> {candidate.age}",
        f"<b>Город:</b> {candidate.city}",
        f"<b>Район / адрес поиска:</b> {candidate.preferred_area or '—'}",
        f"<b>Должность:</b> "
        f"{position_label(candidate.position_normalized, candidate.desired_position)}",
        f"<b>Опыт:</b> {candidate.experience_years} лет",
        f"<b>График:</b> {schedule_label(candidate.schedule)}",
        f"<b>Ожидаемая зарплата:</b> {fmt_money(candidate.expected_salary)} ₸",
        f"<b>Контакт:</b> {candidate.contact}",
    ]
    if candidate.about:
        lines.append(f"<b>О себе:</b> {candidate.about}")
    if candidate.previous_jobs:
        lines.append(f"<b>Опыт работы:</b> {candidate.previous_jobs}")
    if candidate.resume_file_id:
        lines.append("📎 Резюме: прикреплено ✅")
    else:
        lines.append("📎 Резюме: не прикреплено")
    return "\n".join(lines)


def render_vacancy_summary(vacancy: Vacancy) -> str:
    """Полная сводка вакансии для экрана подтверждения / «Мои вакансии»."""
    company = vacancy.employer.company_name if vacancy.employer else "—"
    requirements = requirements_text(vacancy.requirements)
    lines = [
        "🏢 <b>Вакансия</b>\n",
        f"<b>Компания:</b> {company}",
        f"<b>Должность:</b> {position_label(vacancy.position_normalized, vacancy.position)}",
        f"<b>Город:</b> {vacancy.city}",
        f"<b>Адрес:</b> {vacancy.address}",
        f"<b>График:</b> {schedule_label(vacancy.schedule)}",
        f"<b>Зарплата:</b> {fmt_salary_range(vacancy)} ₸",
        f"<b>Требования:</b> {requirements}",
    ]
    if vacancy.conditions:
        lines.append(f"<b>Условия:</b> {vacancy.conditions}")
    return "\n".join(lines)
