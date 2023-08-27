from flask import Flask, request, render_template, redirect, jsonify
from flask_socketio import SocketIO, emit
from hardware import SmartFarmDevice, DEFAULT_MIN_TEMP, DEFAULT_OFF_TIME, DEFAULT_ON_TIME
from datetime import datetime
from time import strftime
import time
from PIL import Image
import numpy as np
import RPi.GPIO as GPIO
import base64
from functools import wraps
import sqlite3
	
app = Flask(__name__)
socketio = SocketIO(app)
# 사용자 로그인 성공 여부
authenticated = False 


class FlaskAppWrapper:
    def __init__(self, app):
        ## self.datas의 구조
        # 개별 data의 구조는 {"timestamp" : "2023.08.08 07:11:09"와 같은 형태의 문자열, "temperature":float, "humidity":float, "water_level" : float
        # "led_first_state" : str ('ON'/'OFF'), "led_second_state" : str ('ON'/'OFF'), "heater_state" : str ('ON'/'OFF'), "pump_state" : str ('ON'/'OFF')}
        # self.datas는 위 개별 data들'을 시간순서대로 모아둔 list임
        self.con_data = sqlite3.connect("./datas.db")  # DATA 저장용
        self.con_setting = sqlite3.connect("./settings.db")  # SETTING 저장용
        self.cur_data = self.con_data.cursor()
        self.cur_setting = self.con_setting.cursor()

        # 데이터 저장용 테이블 있는지 확인
        self.cur_data.execute(
            "SELECT count(name) FROM sqlite_master WHERE type='table' AND name = 'measurements';"
        )
        count_data_table = self.cur_data.fetchone()[0]
        if count_data_table == 0:
            print("[app.__init__] : datas.db에 measurements 테이블이 존재하지 않습니다!")
            self.cur_data.execute(
                """CREATE table measurements(
								timestamp TEXT PRIMARY KEY,
								temperature REAL,
								humidity REAL,
								water_level REAL,
								led_first_state TEXT,
								led_second_state TEXT,
								heater_state TEXT,
								pump_state TEXT);"""
            )
            self.con_data.commit()  # 수정사항 반영
        else :
            print("[app.__init__]: datas.db에 measurements 테이블이 존재합니다.")

        # 설정 저장용 테이블 있는지 확인
        self.cur_setting.execute(
            "SELECT count(name) FROM sqlite_master WHERE type='table' AND name='settings';"
        )
        count_setting_table = self.cur_setting.fetchone()[0]
        if count_setting_table == 0:  # 만약 설정 저장용 테이블 없으면 만들고 기본값 넣음
            print("[app.__init__]: settings.db에 settings 테이블이 존재하지 않습니다!")
            self.cur_setting.execute(
                """CREATE table settings(
                                        ref_temperature REAL,
				        ref_turn_on_time TEXT,
				        ref_turn_off_time TEXT);"""
            )
            self.con_setting.commit()  # 수정사항 반영
            default_min_temp_str = DEFAULT_MIN_TEMP
            default_on_time_str = DEFAULT_ON_TIME.strftime("%H:%M")
            default_off_time_str = DEFAULT_OFF_TIME.strftime("%H:%M")
            query = f"""INSERT INTO settings(
                        ref_temperature,
                        ref_turn_on_time,
                        ref_turn_off_time)
                    VALUES(
                        {default_min_temp_str},
                        '{default_on_time_str}',
                        '{default_off_time_str}');
                 """
            self.cur_setting.execute(query)
            self.con_setting.commit()  # 수정사항 반영
        else :
            print("[app.__init__]: settings.db에 settings 테이블이 존재합니다.")

        # 저장된 설정값들 불러오기
        # -> (ref_temperature, ref_turn_on_time, ref_turn_off_time) 이렇게 받아옴
        self.reference_status = list(self.cur_setting.execute(
            "SELECT * FROM settings;"
        ).fetchone())
        ref_temp = self.reference_status[0]
        # 켤시각과 끌 시각은 datetime.time형으로 전달해야하기 때문에 문자열에서 datetime.time 형으로 변환함
        ref_turn_on_time = datetime.strptime(self.reference_status[1], "%H:%M").time()
        ref_turn_off_time = datetime.strptime(self.reference_status[2], "%H:%M").time()
        print("[app.__init__] 설정된 초기값들")
        print(f"    - 설정 최소 온도 : {ref_temp}")
        print(f"    - 설정된 켜는 시각 : {ref_turn_on_time}")
        print(f"    - 설정된 끄는 시각 : {ref_turn_off_time}")

        self.app = app
        self.smartfarm = SmartFarmDevice(ref_temp, ref_turn_on_time, ref_turn_off_time)

        # 라우팅
        self.setup_route()

        # background thread 시작함
        background_emit_measurement_thread = socketio.start_background_task(
            self.measure_and_emit_periodically
        )

	# TODO:카메라 관련 주석 풀기        
	# background_streaming_thread = socketio.start_background_task(self.update_image_periodically)

        # CLEANUP : 스마트팜이 스스로 상태를 계속 조절하는 스레드와 그 스레드용 함수는 app.py가 아니라 hardware.py에 있어야 하고, 스마트팜의 __init__함수에서 스레드가 시작되는게 마땅함!
        background_adjust_thread = socketio.start_background_task(
            self.adjust_periodically
        )

    def convert_state(self, i):
        """
        스마트팜 객체가 사용하는 GPIO.HIGH, GPIO.LOW와 같은 state를 "ON"이나 "OFF"로 변환해주는 함수.
        """
        if i == GPIO.HIGH:
            return "ON"
        elif i == GPIO.LOW:
            return "OFF"
        else:
            return i

    def setup_route(self):
        """
        모든 url들에 대해 함수들을 라우팅 시키는 셋업 함수
        """
        ## URL 라우팅하는 app_url_rule에는 순서대로
        # 1) rule : '/index' 같은 url
        # 2) endpoint_name : url_for로 이 url을 얻어올 수 있도록 배정된 함수의 이름
        # 3) handler 함수
        # 4) methods (요청방식)
        self.app.add_url_rule("/", "index", self.index, methods=["GET"])
        self.app.add_url_rule("/auth", "authenticate", self.authenticate, methods=["POST"])
        self.app.add_url_rule("/stats", "stats", self.stats, methods=["GET"])
        self.app.add_url_rule("/not_login.html", "not_login", self.login_required, methods=["GET"])
        self.app.add_url_rule("/control", "control", self.control, methods=["GET"])
        self.app.add_url_rule("/control/set_temp", "set_temp", self.set_temp, methods=["POST"])
        self.app.add_url_rule("/control/set_time_period","set_time_period",self.set_time_period,methods=["POST"])
        self.app.add_url_rule("/streaming", "streaming", self.streaming, methods=["GET"])

    def measure_and_emit_periodically(self):
        """
        30초에 한번씩 주기적으로 스마트팜의 측정값들을 갱신하고 얻은 측정값들을 'give_data'란 이벤트 이름으로 emit하는 스레드용 함수
        """
        con_data = sqlite3.connect("./datas.db", check_same_thread = False)  # 다른 스레드에서 쓰기 위한 Data 저장용 DB connection을 하나 더 만듬.. 그냥 self.con_data 객체 쓰면 오류나더라고
        cur_data = con_data.cursor()
        while True:
            print("[app.measure_and_emit_periodically() 실행됨]")
            start_time = time.time()

            # 스마트팜 측정 후 데이터 얻음
            self.smartfarm.measure_temp_and_humidity()
            self.smartfarm.measure_water_level()
            temperature = self.smartfarm.get_temperature()
            humidity = self.smartfarm.get_humidity()
            water_level = self.smartfarm.get_water_level()
            led_first_state = self.smartfarm.get_led_first_state()
            led_second_state = self.smartfarm.get_led_second_state()
            heater_state = self.smartfarm.get_heater_state()
            pump_state = self.smartfarm.get_pump_state()

            # emit 및 저장을 위해 데이터를 가공
            now = datetime.now()
            now_str = now.strftime("%Y.%m.%d %H:%M:%S")
            name = [
                "recent_timestamp",
                "humidity",
                "temperature",
                "water_level",
                "led_first_state",
                "led_second_state",
                "heater_state",
                "pump_state",
            ]
            states = list(
                map(self.convert_state, [led_first_state, led_second_state, heater_state, pump_state])
            )
            data_dict = dict(
                zip(name, [now_str, humidity, temperature, water_level] + states)
            )  # 만든 결과 dict

            con_data = sqlite3.connect("./datas.db", check_same_thread=False)
            cur_data = con_data.cursor() 
            cur_data.execute(
                f"""INSERT INTO measurements
                    VALUES (
                        '{now_str}',
                        {humidity:.1f},
                        {temperature:.1f},
                        {water_level:.1f},
			                  '{self.convert_state(led_first_state)}',
			                  '{self.convert_state(led_second_state)}',
                        '{self.convert_state(heater_state)}',
			                  '{self.convert_state(pump_state)}');
                """)
            con_data.commit()

            # 이전 emit으로부터 30초가 흐를때까지 기다림
            # 참고 : flask-socketio.readthedocs.io/en/latest/api.html#flask_socketio.SocketIO.sleep (비동기 멈춤)
            end_time = time.time()
            if 30 - (end_time - start_time) > 0:
                print(
                    f"    [app.acquire_and_emit_periodically] : {30 - (end_time - start_time)} 만큼 기다립니다."
                )
                socketio.sleep(30 - (end_time - start_time))

            # 이벤트 이름 'give_data'로 데이터 data_dict를 emit -> stats.html에 적힌 자바스크립트에서 처리해 그래프에 추가할 것
            with self.app.app_context() as context:
                socketio.emit(
                    "give_data", data_dict
                )  # socketio.emit 함수를 사용할때는 jsonify()를 사용하지 말고 그냥 딕셔너리 형태의 데이터를 주어야 함!
                # 참고 : https://stackoverflow.com/questions/75004494/typeerror-object-of-type-response-is-not-json-serializable-2

    def adjust_periodically(self):
        """
        1초에 한번씩 smartfarm.adjust 함수를 실행시키는 스레드용 함수
        """
        # CLEANUP : 스마트팜이 스스로 상태를 계속 조절하는 스레드와 그 스레드용 함수는 app.py가 아니라 hardware.py에 있어야 하고, 스마트팜의 __init__함수에서 그 스레드가 시작되는게 마땅함!
        while True:
            self.smartfarm.adjust()
            socketio.sleep(1)

    def index(self):
        """
        '/' 로 요청이 들어왔을 때 index.html을 보여주는 view 함수
        """
        return render_template("index.html")

    def authenticate(self):
        """
        index.html창에서 로그인 정보를 받아 '/auth'로 POST 요청을 주었을 때 주어진 정보로 인증하는 함수.
        인증이 성공하면 '/stats'로 리디렉션하고 실패하면 다시 원래 URL인 '/'으로 리디렉션함.
        """
        global authenticated
        id = request.form.get("id")
        pw = request.form.get("password")

        # 아이디와 비밀번호 확인
        if id == "admin" and pw == "chungju_h@1":
            authenticated = True
            return redirect("stats")
        else:
            return redirect(request.referrer)

    def login_required(func):
        """
        로그인이 되어있을때만 view 함수가 실행될 수 있도록 제어할 데코레이터용 함수
        """

        @wraps(func)
        def decorated_view(*args, **kwargs):
            global authenticated
            if authenticated == True:
                return func(*args, **kwargs)
            else:
                return render_template("not_login.html")

        return decorated_view

    # TODO(정우) : 히터 상태, 1/2층 불 상태도 화면에 표시하도록 하기
    @login_required
    def stats(self):
        """
        '/stats'에 GET 요청이 들어왔을 때 stats.html을 반환하는 view 함수
        """
        # 초기 그래프를 그릴 데이터들을 가져옴
        con_data = sqlite3.connect("./datas.db", check_same_thread=False)
        cur_data = con_data.cursor()
        recent_datas = cur_data.execute(
            "SELECT * FROM measurements ORDER BY timestamp DESC;"
        ).fetchmany(6)  # 최근 6개 데이터
        con_data.close()

        recent_datas.reverse()
        recent_timestamps = [data[0] for data in recent_datas]
        recent_timestamp = recent_timestamps[-1]
        initial_humidities = [data[1] for data in recent_datas]
        initial_temperatures = [data[2] for data in recent_datas]
        initial_water_levels = [data[3] for data in recent_datas]

        led_first_state = self.convert_state(self.smartfarm.get_led_first_state())
        led_second_state = self.convert_state(self.smartfarm.get_led_second_state())
        heater_state = self.convert_state(self.smartfarm.get_heater_state())
        pump_state = self.convert_state(self.smartfarm.get_pump_state())


        print(f"[app.stats (GET)] : 화면에 표시할 데이터들을 출력합니다 : ")
        print(f"    recent_timestamp :{recent_timestamp}")
        print(f"    initial_humidities :{initial_humidities}")
        print(f"    initial_temperatures :{initial_temperatures}")
        print(f"    initial_water_levels :{initial_water_levels}")
        print(f"    led_first_state : {led_first_state}")
        print(f"    led_second_state : {led_second_state}")
        print(f"    heater_state : {heater_state}")
        print(f"    pump_state : {pump_state}")
        # 맨 처음 stats.html을 서버에서 보내줄 때 초기 그래프에 표시될 데이터를 같이 주면
        # stats.html 자바스크립트 부분 초기 데이터 템플릿에 들어감
        return render_template(
            "stats.html",
            recent_timestamps = recent_timestamps,
            recent_timestamp = recent_timestamp,
            initial_temperatures=initial_temperatures,
            initial_heights=initial_water_levels,
            initial_humidities=initial_humidities,
            led_first_state = led_first_state,
            led_second_state = led_second_state,
            heater_state = heater_state,
            pump_state = pump_state,
        )

    @login_required
    def control(self):
        """
        '/control' 로 GET 요청이 들어왔을 때 control.html을 반환하는 view 함수
        """
        # 위쪽의 background_task 함수에서 값을 얻어오고 딕셔너리 안에 넣어서 넘겨줘야함, 변수명 이래 직접써도 될라나모르겄다
        cur_status = {
            "cur_temperature": self.smartfarm.get_temperature(),
            "cur_humidity": self.smartfarm.get_humidity(),
            "cur_water_level": self.smartfarm.get_water_level(),
            "cur_first_light_state": self.smartfarm.get_led_first_state(),
            "cur_second_light_state": self.smartfarm.get_led_second_state(),
            "cur_heater_state": self.smartfarm.get_heater_state(),
            "cur_pump_state": self.smartfarm.get_pump_state(),
        }

        reference_status = {
            "ref_temperature" : self.reference_status[0],
            "ref_turn_on_time" : self.reference_status[1],
            "ref_turn_off_time" : self.reference_status[2],
        }
        print(f"cur_status : {cur_status}")
        reference_status = dict()
        reference_status['ref_temperature'] = self.reference_status[0]
        reference_status['ref_turn_on_time'] = self.reference_status[1]
        reference_status['ref_turn_off_time'] = self.reference_status[2]
        print(f"reference_status : {reference_status}")
        return render_template(
            "control.html",
            code=True,
            cur_status=cur_status,
            reference_status = reference_status
        )

    @login_required
    def set_temp(self):
        """
        '/control/set_temp'로 POST 요청이 들어왔을 때 사용자 설정 최저 온도를 request.form의 설정 온도로 갱신하는 함수
        """
        _temp = request.form.get("new_temp_reference")
        print(f"[app.set_temp()] : _temp : {_temp} (type : {type(_temp)})")
        try:
            temp = float(_temp)
            self.smartfarm.set_min_temp(temp)
            # CLEANUP : ref보다 setting으로 표현하는게 더 이해하기 쉬운듯. app.py에 사용되는 변수명과 control.html에 쓰이는 변수명들을 모두 바꾸는 것이 어떨까?
            # UPDATE를 이용해 오직 한개의 레이블만 사용할 것
            self.reference_status[0] = temp
            con_setting = sqlite3.connect('./settings.db', check_same_thread = False)
            cur_setting = con_setting.cursor()
            cur_setting.execute(
                f"""UPDATE settings
                    SET ref_temperature = {temp:.1f}
                """)
            con_setting.commit()
            con_setting.close()
            return redirect(request.referrer)
        
        except ValueError as e:
            print("[app.set_temp] 허용되지 않은 입력이 존재합니다.")
            return redirect(request.referrer, code="temp_invalid")

    @login_required
    def set_time_period(self):
        """
        '/control/set_time_period'로 POST 요청이 들어왔을 때 사용자 설정 최저 온도를 request.form의 설정 온도로 갱신하는 함수
        """
        on_time_str = request.form["new_turn_on_time_reference"]
        off_time_str = request.form["new_turn_off_time_reference"]
        print(
            f"[app.set_time_period] : on_time_str : {on_time_str} ({type(on_time_str)})"
        )
        print(
            f"[app.set_time_period] : off_time_str : {off_time_str} ({type(off_time_str)})"
        )

        if on_time_str == off_time_str:
            print("[app.time_period] : 입력받은 두 시각이 동일합니다!")
            return redirect("/control", code="time_same")

        try:
            # smartfarm에는 datetime.datetime 형으로 넘겨줘야해서 형변환 시켜줌
            on_time = datetime.strptime(on_time_str, "%H:%M").time()
            off_time = datetime.strptime(off_time_str, "%H:%M").time()
            # 다른 스레드에서는 또다른 커넥션 객체를 만들어 작업해주어야함..
            con_setting = sqlite3.connect('./settings.db', check_same_thread = False)
            cur_setting = con_setting.cursor()
            self.smartfarm.set_on_time(on_time)
            self.smartfarm.set_off_time(off_time)
            self.reference_status[1] = on_time_str
            self.reference_status[2] = off_time_str
            con_setting = sqlite3.connect("./settings.db", check_same_thread=False)
            cur_setting = con_setting.cursor()
            cur_setting.execute(
                f"""
                UPDATE settings 
                SET ref_turn_on_time = '{on_time_str}',
                    ref_turn_off_time = '{off_time_str}';
                """
            )
            con_setting.commit()
            con_setting.close()
            return redirect("/control")
        except ValueError as e:
            print("[app.time_period] 허용되지 않은 입력이 존재합니다.")
            return redirect("/control", code="time_invalid")

    @login_required
    def streaming(self):
        """
        '/streaming'으로 GET 요청이 들어왔을 때 streaming.html을 반환하는 view 함수
        """
        return render_template("streaming.html")

    def update_image_periodically(self):
        """
        6초에 한번씩 스마트팜으로부터 이미지를 얻어 'give_image'란 이벤트 이름으로 이미지를 byte형으로 emit하는 스레드용 함수.
        30초에 한번씩은 스마트팜에서 얻은 byte형 이미지를 로컬에 측정시각을 파일 이름으로 하여 jpeg로 저장함.
        """
        last_saved_time = time.time()
        last_emit_time = time.time()
        while True:
            print("[update_image_periodically 실행됨]")
            current_time = time.time()
            # 사진을 파일로 저장하는 주기는 30초로하고, 30초 이전에는 저장 없이 스트림에서 byte64로 이미지만 가져옴
            # CLEANUP : 이미지를 파일로 저장하는 기능은 스마트팜이 아니라 서버에서 구현하는게 맞을듯. 스마트팜의 get_image에 save_to_file을 인자로 주어 그에 맞게 스마트팜에서 이미지를 저장하거나 저장하지 않도록 하는 것이 아니라,
            #           스마트팜은 단순히 이미지를 찍어 byte로 리턴하고, 저장은 서버의 update_image_periodically 함수에서 하자
            if current_time - last_saved_time >= 30:
                byte_image = self.smartfarm.get_image(save_to_file=True)
                last_saved_time = current_time
            else:
                byte_image = self.smartfarm.get_image(save_to_file=False)

            # 사진을 보낸 시간이 6초가 안지났으면 6초 될때까지 기다림
            if (current_time - last_emit_time) < 6:
                # print(f"  [update_image_periodically] async sleep for {6 - (current_time - last_emit_time) :.3f} seconds")
                socketio.sleep(6 - (current_time - last_emit_time))
            last_emit_time = time.time()

            socketio.emit("give_image", {"byte_image": byte_image})


if __name__ == "__main__":
    # flask 앱과 스마트팜을 wrap한 객체 만들고
    wrapper = FlaskAppWrapper(app)
    # 앱 실행시킴
    socketio.run(app)
