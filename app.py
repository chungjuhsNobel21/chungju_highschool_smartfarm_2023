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

app = Flask(__name__)
socketio = SocketIO(app)


def convert_state(i):
    if i == GPIO.HIGH:
        return "ON"
    elif i == GPIO.LOW :
        return "OFF"
    else:
        return i

class FlaskAppWrapper():
    def __init__(self, app, datas, reference_status, data_pickle_file_stream, setting_pickle_file_stream):
        self.app = app
        self.smartfarm = smartFarm_Device()

        # TODO (정수) : authentication 기능 구현하여 로그인창 제외 다른 창에 로그인 못한 사용자가 접근 못하도록 막기
        #               만약 로그인 안한 사용자가 접근 불가능한 다른 창에 접근하려고 하면 not_login.html 반환하기 
        # 사용자 로그인 성공 여부
        # TODO: 배포시 False로 바꾸기
        self.authenticated = True

        
        self.data_pickle_file_stream = data_pickle_file_stream
        self.setting_pickle_file_stream = setting_pickle_file_stream
        
        # 라우팅
        self.setup_route()
        
        # background_thread 시작함
        # TODO : start_background_task 작동하는지 확인
        background_thread = socketio.start_background_task(self.background_task)
        background_streaming_thread = socketio.start_background_task(self.update_image_periodically)

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
        self.app.add_url_rule('/control', 'control', self.control, methods=['GET'])
        self.app.add_url_rule('/control/set_temp', 'set_temp', self.set_temp, methods=['POST'])
        self.app.add_url_rule('/control/set_time_period', 'set_time_period', self.set_time_period, methods=['POST'])
        self.app.add_url_rule('/streaming', 'streaming', self.streaming, methods=['GET'])

    # TODO (기훈) : background_task 실제 서버 운영 스레드와 함께 정상 작동하도록 스레드 흐름 고치기
    def background_task(self):
        while True:
            print("[app.background_task() 실행됨]")
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
            
            now = datetime.now()
            now_str = now.strftime("%Y.%m.%d %H:%M:%S")
            
            name = ["timestamp","humidity","temperature", "water_level", "first_light_state", "second_light_state", "heater_state", "pump_state"]
            a = list(map(convert_state, [now_str, humidity,temperature, water_level, first_light_state, second_light_state, heater_state, pump_state]))
            # emit할 dict
            data_dict = dict(zip(name, a))
            self.datas.append(data_dict)
            
            # 이전 emit으로부터 30초가 흐를때까지 기다린 후 다음 emit을 진행함
            # 참고 : flask-socketio.readthedocs.io/en/latest/api.html#flask_socketio.SocketIO.sleep
            end_time = time.time()
            if 30 - (end_time - start_time) > 0 :
                print(f"[background_task] : {30 - (end_time - start_time)} 만큼 기다립니다.")
                socketio.sleep(30 - (end_time - start_time))
        
            # 만약 사용자가 인증되어있으면 give_data 이벤트 이름으로 data_dict 보냄
            # give_data 이벤트 이름으로 보낸 data_dict 데이터는 stats.html에 적힌 자바스크립트에서 처리해 그래프에 추가할 것임
            if self.authenticated == True :
                with self.app.app_context() as context :                
                    
                    # socketio.emit 함수를 사용할때는 jsonify()를 사용하지 말고 그냥 딕셔너리 형태의 데이터를 주어야 함! 
                    # https://stackoverflow.com/questions/75004494/typeerror-object-of-type-response-is-not-json-serializable-2
                    socketio.emit('give_data', data_dict)
            
    def index(self):
        return render_template('index.html')

    def authenticate(self):
        id = request.form.get('id')
        pw = request.form.get('password')

        # 아이디와 비밀번호 확인
        if id == 'admin' and pw == 'chungju_h@1':
            self.authenticated = True
            return redirect('stats')
        else :
            return redirect(request.referrer)

    # TODO(정우) : 히터 상태, 1/2층 불 상태도 화면에 표시하도록 하기
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
    
    def control(self):
        #  TODO(태현) : 현재 설정값을 보여주는 text 만들어서 최초 Flask Jinja 템플릿 기능으로 현재 설정된 스마트팜 상태값을 보여주기
        # 위쪽의 background_task 함수에서 값을 얻어오고 딕셔너리 안에 넣어서 넘겨줘야함, 변수명 이래 직접써도 될라나모르겄다
        cur_status ={
            'cur_temperature':self.smartfarm.get_temperature() or 26,
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
    
    
    def set_temp(self):
        _temp = request.form.get('new_temp_reference')
        print(f"[app.set_temp()] : _temp : {_temp} (type : {type(_temp)})")
        try :
            temp = float(_temp)
            self.smartfarm.set_min_temp(temp)
            # TODO(코드클리닝) : 태현이 변수 리네임하면서 코드 클리닝 ㄱㄱ
            self.reference_status['ref_temperature'] = temp
            return redirect(request.referrer)
        except ValueError as e :
            # TODO(태현) :Flask Jinja 템플릿 기능 이용해서 백엔드에서 입력 처리후 만약 허용되지 않은 입력(ex: 온도인데 '앙'같은 문자)이면 허용되지 않은 입력이라는 메시지 보내기
            print("[app.set_temp] 허용되지 않은 입력이 존재합니다.")
            return redirect(request.referrer, code=False)
        
    def set_time_period(self):     
        _on_time = request.form['new_turn_on_time_reference']
        _off_time = request.form['new_turn_off_time_reference']
        print(f"[app.set_time_period] : _on_time : {_on_time} ({type(_on_time)})")
        print(f"[app.set_time_period] : _off_time : {_off_time} ({type(_off_time)})")
            
        try :
            # smartfarm에는 datetime.datetime 형으로 넘겨줘야해서 형변환 시켜줌
            on_time = time.strptime(_on_time, '%H:%M')
            off_time = time.strptime(_off_time, '%H:%M')
            self.smartfarm.set_on_time(on_time)
            self.smartfarm.set_off_time(off_time)
            self.reference_status['ref_turn_on_time'] = _on_time
            self.reference_status['ref_turn_off_time'] = _off_time
            return redirect('/control')
        except ValueError as e :
            # TODO(태현) :Flask Jinja 템플릿 기능 이용해서 백엔드에서 입력 처리후 만약 허용되지 않은 입력(ex: 온도인데 '앙'같은 문자)이면 허용되지 않은 입력이라는 메시지 보내기
            print("[app.time_period] 허용되지 않은 입력이 존재합니다.")
            return redirect('/control', code=False)

    def streaming(self):
        return render_template('streaming.html')

    def update_image_periodically(self):
        last_saved_time = time.time()
        last_emit_time = time.time()
        while True:
            print("[update_image_periodically 실행됨]")
            current_time = time.time()
            # 사진을 파일로 저장하는 주기는 30초로하고, 30초 이전에는 저장 없이 스트림에서 byte64로 이미지만 가져옴
            if current_time - last_saved_time >= 30:
                encoded_image = self.smartfarm.get_image(save_to_file=True)
            else :
                encoded_image = self.smartfarm.get_image(save_to_file=False)
            # 사진을 보낸 시간이 0.1초가 안지났으면 0.1초가 될때까지 기다림
            if (current_time - last_emit_time) < 0.1 :
                socketio.sleep(0.1 - (current_time - last_emit_time))
                last_emit_time = current_time

            socketio.emit("give_image", {"encoded_image": encoded_image}, broadcast=True)


if __name__ == '__main__':
    # pickle로부터 측정값 가져오기
    
    # 읽기모드는 append, byte형 (pickle은 byte형으로 저장한다는게 중요함)
    ## self.datas의 구조
    # 개별 data의 구조는 {"timestamp" : "2023.08.08 07:11:09"와 같은 형태의 문자열, "temperature":float, "humidity":float, "water_level" : float
    # "first_light_state" : str ('ON'/'OFF'), "second_light_state" : str ('ON'/'OFF'), "heater_state" : str ('ON'/'OFF'), "pump_state" : str ('ON'/'OFF')}
    # self.datas는 위 개별 data들'을 시간순서대로 모아둔 list임
    with open('measure_data_pickle', 'rb') as pickle_file:
        try :
            datas = pickle.load(pickle_file)
        except EOFError as e :
            print("불러올 pickle 측정값 데이터가 없음")
            datas = list()
    
    #pickle로부터 설정값 가져오기
    
    # TODO(코드클리닝)- 확장자
    ## self.last_setting의 구조
    # {'ref_temperature' : (설정된 최저온도 값), 'ref_turn_on_time' :(설정된 켤 시각 "07:11:09"와 같은 문자열), 'ref_turn_off_time' :(설정된 끌 시각)}
    with open('setting_data_pickle.pickle', 'rb') as pickle_file:
        try :
            reference_status = pickle.load(pickle_file)
        except EOFError as e :
            print("불러올 pickle 설정값 데이터가 없음")
            # 불러올 유저 세팅값이 없으면 기본 세팅값을 맞춤
            reference_status = {'ref_temperature' : 19,
                                 'ref_turn_on_time' :"06:00:00",
                                 'ref_turn_off_time' :"18:00:00"}
            
    # 웹서버가 파일을 적기 위한 파일 스트림을 연결하고 객체에 전달하고 실행함.
    # with 구문을 사용했기 때문에 서버가 종료되면 자동으로 파일이 닫히고 저장됨
    with open('measure_data_pickle.pickle', 'ab'), open('setting_data_pickle.pickle', 'ab') as data_pickle_file_stream, setting_pickle_file_stream:        
        app_wrapper = FlaskAppWrapper(app, datas, reference_status, data_pickle_file_stream, setting_pickle_file_stream)
        socketio.run(app)