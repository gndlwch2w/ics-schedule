import json
import time
import requests
from fake_useragent import UserAgent
from api import ClassScheduleResolver

class YNUGraduateClassScheduleResolver(ClassScheduleResolver):
    def __init__(self, cookies):
        self.ua_generator = UserAgent()
        self.cookies = cookies

    def parser(self, res):
        def parse_week_str(week_str):
            s, t = week_str[:-1].split("-")
            return list(range(int(s), int(t) + 1))

        # 解析课程信息
        course_info = {}
        for e in res["results"]:
            name = e["KCMC"]
            if course_info.get(name) is None:
                course_info[name] = {
                    "name": name,
                    "position": e["JASMC"],
                    "teacher": e["JSXM"],
                    "weeks": parse_week_str(e["ZCMC"]),
                    "day": e["XQ"],
                    "sections": [e["KSJCDM"]]
                }
            else:
                course_info[name]["weeks"].extend(parse_week_str(e["ZCMC"]))
                course_info[name]["sections"].append(e["KSJCDM"])

        # 去除重复数据
        for name, v in course_info.items():
            course_info[name]["weeks"] = list(set(v["weeks"]))
            course_info[name]["sections"] = list(set(v["sections"]))

        def parse_time_int(time_int):
            time_str = str(time_int)
            time_str = f"0{time_str}" if len(time_str) == 3 else time_str
            return f"{time_str[:2]}:{time_str[2:]}"

        # 解析课程节数时间安排
        section_times = []
        raw_section_times = [e for e in json.loads(res["skjcList"]) if e["JCFADM"] == "02"]
        for e in raw_section_times:
            section_times.append({
                "section": int(e["DM"]),
                "start_time": parse_time_int(e["KSSJ"]),
                "end_time": parse_time_int(e["JSSJ"])
            })

        return {
            "course_info": list(course_info.values()),
            "section_times": section_times
        }

    def provider(self):
        api = "https://yjsxk.ynu.edu.cn/yjsxkapp/sys/xsxkapp/xsxkCourse/loadKbxx.do"
        params = {
            "_": int(time.time() * 1000)
        }
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Host": "yjsxk.ynu.edu.cn",
            "Referer": "https://yjsxk.ynu.edu.cn/yjsxkapp/sys/xsxkapp/course.html",
            "Cookie": self.cookies,
            "User-Agent": self.ua_generator.chrome
        }
        return requests.get(api, params=params, headers=headers, verify=False).json()
