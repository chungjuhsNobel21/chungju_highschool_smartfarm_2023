from flask import Flask, request, render_template, redirect, jsonify
from flask_socketio import SocketIO, emit
from hardware import smartFarm_Device
from datetime import datetime
from time import strftime
import pickle
import time
from PIL import Image
import numpy as np
import RPi.GPIO as GPIO
import base64
from functools import wraps

app = Flask(__name__)
socketio = SocketIO(app)
# 사용자 로그인 성공 여부
authenticated = False

def convert_state(i):
    if i == GPIO.HIGH:
        return "ON"
    elif i == GPIO.LOW :
        return "OFF"
    else:
        return i

# TODO: pickle 파일 저장 제대로 되는지 확인하기

class FlaskAppWrapper():
    def __init__(self, app, datas, reference_status):
        self.datas = datas # 이전까지의 측정값 데이터들
        self.session_new_datas = list() # 이번 세션에서 새롭게 측정한 데이터들을 모을 리스트 -> 앱 종료시 이것만 피클 파일에 이어붙임
        self.reference_status = reference_status


        ref_temp = self.reference_status['ref_temperature']
        # 켤시각과 끌 시각은 datetime.time형으로 전달해야하기 때문에 문자열에서 datetime.time 형으로 변환함
        ref_turn_on_time = datetime.strptime(self.reference_status['ref_turn_on_time'], "%H:%M").time()
        ref_turn_off_time = datetime.strptime(self.reference_status['ref_turn_off_time'], "%H:%M").time()
        print("[app.__init__] 설정된 초기값들")
        print(f"    - 설정 최소 온도 : {ref_temp}")
        print(f"    - 설정된 켜는 시각 : {ref_turn_on_time}")
        print(f"    - 설정된 끄는 시각 : {ref_turn_off_time}")

        self.app = app
        self.smartfarm = smartFarm_Device(ref_temp, ref_turn_on_time, ref_turn_off_time)
        
        # 라우팅
        self.setup_route()
        
        # background thread 시작함
        background_emit_measurement_thread = socketio.start_background_task(self.measure_and_emit_periodically)
        # background_streaming_thread = socketio.start_background_task(self.update_image_periodically)

        # CLEANUP : 스마트팜이 스스로 상태를 계속 조절하는 스레드와 그 스레드용 함수는 app.py가 아니라 hardware.py에 있어야 하고, 스마트팜의 __init__함수에서 스레드가 시작되는게 마땅함!
        background_adjust_thread = socketio.start_background_task(self.adjust_periodically)

    def setup_route(self):
        '''
        모든 url들에 대해 함수들을 라우팅 시키는 셋업 함수
        '''
        ## URL 라우팅하는 app_url_rule에는 순서대로
        # 1) rule : '/index' 같은 url
        # 2) endpoint_name : url_for로 이 url을 얻어올 수 있도록 배정된 함수의 이름
        # 3) handler 함수
        # 4) methods (요청방식)
        self.app.add_url_rule('/', 'index', self.index, methods=['GET'])
        self.app.add_url_rule('/auth', 'authenticate', self.authenticate, methods=['POST'])
        self.app.add_url_rule('/stats', 'stats', self.stats, methods=['GET'])
        self.app.add_url_rule('/not_login.html', 'not_login', self.login_required, methods=['GET'])
        self.app.add_url_rule('/control', 'control', self.control, methods=['GET'])
        self.app.add_url_rule('/control/set_temp', 'set_temp', self.set_temp, methods=['POST'])
        self.app.add_url_rule('/control/set_time_period', 'set_time_period', self.set_time_period, methods=['POST'])
        self.app.add_url_rule('/streaming', 'streaming', self.streaming, methods=['GET'])

    def measure_and_emit_periodically(self):
        '''
        30초에 한번씩 주기적으로 스마트팜의 측정값들을 갱신하고 얻은 측정값들을 'give_data'란 이벤트 이름으로 emit하는 스레드용 함수
        '''
        while True:
            print("[app.measure_and_emit_periodically() 실행됨]")
            start_time = time.time()

            # 스마트팜 측정 후 데이터 얻음
            self.smartfarm.measure_temp_and_humidity()
            self.smartfarm.measure_water_level()
            temperature = self.smartfarm.get_temperature()
            humidity = self.smartfarm.get_humidity()
            water_level = self.smartfarm.get_water_level() 
            first_light_state, second_light_state = self.smartfarm.get_light_state()
            heater_state = self.smartfarm.get_heater_state()
            pump_state = self.smartfarm.get_pump_state()
            
            # emit 및 저장을 위해 데이터를 가공
            now = datetime.now()
            now_str = now.strftime("%Y.%m.%d %H:%M:%S")            
            name = ["timestamp","humidity","temperature", "water_level", "first_light_state", "second_light_state", "heater_state", "pump_state"]
            states = list(map(convert_state, [first_light_state, second_light_state, heater_state, pump_state])) 
            data_dict = dict(zip(name, [now_str, humidity, temperature, water_level] + states)) # 만든 결과 dict

            # 만든 결과를 저장
            self.datas.append(data_dict) # 기존 데이터들까지 가지고 있는 측정값들 리스트
            self.session_new_datas.append(data_dict) # 현재 서버 세션에서 새롭게 측정된 측정값들 리스트

            # 이전 emit으로부터 30초가 흐를때까지 기다림
              # 참고 : flask-socketio.readthedocs.io/en/latest/api.html#flask_socketio.SocketIO.sleep (비동기 멈춤)
            end_time = time.time()
            if 30 - (end_time - start_time) > 0 :
                print(f"    [app.acquire_and_emit_periodically] : {30 - (end_time - start_time)} 만큼 기다립니다.")
                socketio.sleep(30 - (end_time - start_time))
        
            # 이벤트 이름 'give_data'로 데이터 data_dict를 emit -> stats.html에 적힌 자바스크립트에서 처리해 그래프에 추가할 것
            with self.app.app_context() as context :                
                socketio.emit('give_data', data_dict)   # socketio.emit 함수를 사용할때는 jsonify()를 사용하지 말고 그냥 딕셔너리 형태의 데이터를 주어야 함! 
                                                          # 참고 : https://stackoverflow.com/questions/75004494/typeerror-object-of-type-response-is-not-json-serializable-2
    def adjust_periodically(self):
        '''
        1초에 한번씩 smartfarm.adjust 함수를 실행시키는 스레드용 함수
        '''
        # CLEANUP : 스마트팜이 스스로 상태를 계속 조절하는 스레드와 그 스레드용 함수는 app.py가 아니라 hardware.py에 있어야 하고, 스마트팜의 __init__함수에서 그 스레드가 시작되는게 마땅함!
        while True:
            self.smartfarm.adjust()        
            socketio.sleep(1)
    

    def index(self):
        return render_template('index.html')

    def authenticate(self):
        global authenticated
        id = request.form.get('id')
        pw = request.form.get('password')

        # 아이디와 비밀번호 확인
        if id == 'admin' and pw == 'chungju_h@1':
            authenticated = True
            return redirect('stats')
        else :
            return redirect(request.referrer)

    def login_required(func):
        @wraps(func)
        def decorated_view(*args, **kwargs):
            global authenticated
            if authenticated == True:
                return func(*args, **kwargs)
            else:
                return render_template('not_login.html')
        return decorated_view

    # TODO(정우) : 히터 상태, 1/2층 불 상태도 화면에 표시하도록 하기
    @login_required
    def stats(self):
        # 초기 그래프를 그릴 데이터들을 가져옴
        recent_datas = self.datas[-7:-1]    # 최근 6개 데이터
        initial_temperatures = [data['temperature'] for data in recent_datas]
        initial_water_levels = [data['water_level'] for data in recent_datas]
        initial_humidities = [data['humidity'] for data in recent_datas]
        print(f"[stats] initial_temperatures :{initial_temperatures}")
        print(f"[stats] initial_water_levels :{initial_water_levels}")
        print(f"[stats] initial_humidities :{initial_humidities}")
        # 맨 처음 stats.html을 서버에서 보내줄 때 초기 그래프에 표시될 데이터를 같이 주면
        # stats.html 자바스크립트 부분 초기 데이터 템플릿에 들어감
        return render_template('stats.html',
                               initial_temperatures=initial_temperatures,
                               initial_heights = initial_water_levels,
                               initial_humidities = initial_humidities)
    @login_required
    def control(self):
        # 위쪽의 background_task 함수에서 값을 얻어오고 딕셔너리 안에 넣어서 넘겨줘야함, 변수명 이래 직접써도 될라나모르겄다
        cur_status ={
            'cur_temperature':self.smartfarm.get_temperature(),
            'cur_humidity':self.smartfarm.get_humidity(),
            'cur_water_level':self.smartfarm.get_water_level() ,
            'cur_first_light_state' : self.smartfarm.get_light_state()[0],
            'cur_second_light_state':self.smartfarm.get_light_state()[1],
            'cur_heater_state' :self.smartfarm.get_heater_state(),
            'cur_pump_state':self.smartfarm.get_pump_state(),
        }

        print(f"cur_status : {cur_status}")
        print(f"self.reference_status : {self.reference_status}")
        return render_template('control.html',code=True, cur_status=cur_status, reference_status=self.reference_status)
    
    @login_required
    def set_temp(self):
        _temp = request.form.get('new_temp_reference')
        print(f"[app.set_temp()] : _temp : {_temp} (type : {type(_temp)})")
        try :
            temp = float(_temp)
            self.smartfarm.set_min_temp(temp)
            # CLEANUP : ref보다 setting으로 표현하는게 더 이해하기 쉬운듯. app.py에 사용되는 변수명과 control.html에 쓰이는 변수명들을 모두 바꾸는 것이 어떨까?
            self.reference_status['ref_temperature'] = temp
            return redirect(request.referrer)
        except ValueError as e :
            print("[app.set_temp] 허용되지 않은 입력이 존재합니다.")
            return redirect(request.referrer, code='temp_invalid')
    
    @login_required
    def set_time_period(self):     
        on_time_str = request.form['new_turn_on_time_reference']
        off_time_str = request.form['new_turn_off_time_reference']
        print(f"[app.set_time_period] : on_time_str : {on_time_str} ({type(on_time_str)})")
        print(f"[app.set_time_period] : off_time_str : {off_time_str} ({type(off_time_str)})")

        if on_time_str == off_time_str :
            print("[app.time_period] : 입력받은 두 시각이 동일합니다!")
            return redircet('/control', code='time_same')
            
        try :
            # smartfarm에는 datetime.datetime 형으로 넘겨줘야해서 형변환 시켜줌
            on_time = datetime.strptime(on_time_str, '%H:%M').time()
            off_time = datetime.strptime(off_time_str, '%H:%M').time()
            self.smartfarm.set_on_time(on_time)
            self.smartfarm.set_off_time(off_time)
            self.reference_status['ref_turn_on_time'] = on_time_str
            self.reference_status['ref_turn_off_time'] = off_time_str
            return redirect('/control')
        except ValueError as e :
            print("[app.time_period] 허용되지 않은 입력이 존재합니다.")
            return redirect('/control', code='time_invalid')

    @login_required
    def streaming(self):
        return render_template('streaming.html')

    def update_image_periodically(self):
        '''
        6초에 한번씩 스마트팜으로부터 이미지를 얻어 'give_image'란 이벤트 이름으로 이미지를 byte형으로 emit하는 스레드용 함수.
        30초에 한번씩은 스마트팜에서 얻은 byte형 이미지를 로컬에 측정시각을 파일 이름으로 하여 jpeg로 저장함.
        '''
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
            else :
                byte_image = self.smartfarm.get_image(save_to_file=False)

            # 사진을 보낸 시간이 6초가 안지났으면 6초 될때까지 기다림
            if (current_time - last_emit_time) < 6 :
                # print(f"  [update_image_periodically] async sleep for {6 - (current_time - last_emit_time) :.3f} seconds")
                socketio.sleep(6 - (current_time - last_emit_time))
            last_emit_time = time.time()

            socketio.emit("give_image", {"byte_image": byte_image})


if __name__ == '__main__':
    # pickle로부터 측정값 가져오기
    # 읽기모드는 append, byte형 (pickle은 byte형으로 저장한다는게 중요함)
    ## self.datas의 구조
    # 개별 data의 구조는 {"timestamp" : "2023.08.08 07:11:09"와 같은 형태의 문자열, "temperature":float, "humidity":float, "water_level" : float
    # "first_light_state" : str ('ON'/'OFF'), "second_light_state" : str ('ON'/'OFF'), "heater_state" : str ('ON'/'OFF'), "pump_state" : str ('ON'/'OFF')}
    # self.datas는 위 개별 data들'을 시간순서대로 모아둔 list임
    with open('measure_data_pickle', 'rb') as data_pickle_file:
        try :
            datas = pickle.load(data_pickle_file)
        except EOFError as e :
            print("불러올 pickle 측정값 데이터가 없음")
            datas = list()
    
    #pickle로부터 설정값 가져오기
    # TODO(코드클리닝)- 확장자
    ## self.last_setting의 구조
    # {'ref_temperature' : (설정된 최저온도 값), 'ref_turnon_time_str' :(설정된 켤 시각 "07:11"와 같은 문자열), 'ref_turnoff_time_str' :(설정된 끌 시각)}
    with open('setting_data_pickle.pickle', 'rb') as setting_pickle_file:
        try :
            reference_status = pickle.load(setting_pickle_file)
        except EOFError as e :
            print("불러올 pickle 설정값 데이터가 없음")
            # 불러올 유저 세팅값이 없으면 기본 세팅값을 맞춤
            reference_status = {'ref_temperature' : 19,
                                 'ref_turnon_time_str' :"06:00:00",
                                 'ref_turnoff_time_str' :"18:00:00"}
    # flask 앱과 스마트팜을 wrap한 객체 만들고
    wrapper = FlaskAppWrapper(app, datas, reference_status)
    # 앱 실행시킴
    socketio.run(app)

    # 앱 종료후 변경된 데이터들 저장함 - 측정값 데이터들은 새로운 것들만 이어붙이고, 설정값은 아예 덮어쓰기함
    with open('measure_data_pickle', 'ab') as data_pickle_file:
        pickle.dump(wrapper.session_new_datas, data_pickle_file)
    with open('setting_data_pickle', 'wb') as setting_pickle_file:
        pickle.dump(wrapper.reference_status, setting_pickle_file)


 
        
