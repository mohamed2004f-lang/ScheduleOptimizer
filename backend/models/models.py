class Student:
    def __init__(self, student_id: str, student_name: str):
        self.student_id = student_id
        self.student_name = student_name

class Course:
    def __init__(self, course_name: str, course_code: str, units: int):
        self.course_name = course_name
        self.course_code = course_code
        self.units = units

class ScheduleRow:
    def __init__(self, section_id: int, course_name: str, day: str, time: str, room: str, instructor: str, semester: str):
        self.section_id = section_id
        self.course_name = course_name
        self.day = day
        self.time = time
        self.room = room
        self.instructor = instructor
        self.semester = semester

class Grade:
    def __init__(self, student_id: str, semester: str, course_name: str, grade: float):
        self.student_id = student_id
        self.semester = semester
        self.course_name = course_name
        self.grade = grade
