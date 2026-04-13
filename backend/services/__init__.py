# backend.services package init
from .students import students_bp
from .courses import courses_bp
from .grades import grades_bp
from .schedule import schedule_bp

__all__ = ["students_bp", "courses_bp", "grades_bp", "schedule_bp"]
