from flask import Flask, request, render_template, redirect, jsonify
from flask_socketio import SocketIO, emit
from hardware import smartFarm_Device
from datetime import datetime
from time import strftime
import pickle
from PIL import Image
import numpy as np

app = Flask(__name__)
socketio = SocketIO(app)


def convert_state(i):
    if i == "GPIO.HIGH":
        return "ON"
    elif i == "GPIO.LOW" :
        return "OFF"

class FlaskAppWrapper():
    def __init__(self, app, socket):
        self.app = app
        self.smartfarm = smartFarm_Device()
        self.socketio = socket


        # TODO (정수) : authentication 기능 구현하여 로그인창 제외 다른 창에 로그인 못한 사용자가 접근 못하도록 막기
        #               만약 로그인 안한 사용자가 접근 불가능한 다른 창에 접근하려고 하면 not_login.html 반환하기 
        # 사용자 로그인 성공 여부
        self.authenticated = False
        # pickle로부터 데이터 가져오기
        # 읽기모드는 append, byte형 (pickle은 byte형으로 저장한다는게 중요함)
        ## self.datas의 구조
        # 개별 data의 구조는 {"timestamp" : "2023.08.08 07:11:09"와 같은 형태의 문자열, "temperature":float, "humidity":float, "water_level" : float
        # "first_light_state" : str ('ON'/'OFF'), "second_light_state" : str ('ON'/'OFF'), "heater_state" : str ('ON'/'OFF'), "pump_state" : str ('ON'/'OFF')}
        # self.datas는 위 개별 data들'을 시간순서대로 모아둔 list임
        with open('measure_data_pickle', 'rb') as pickle_file:
            try :
                self.datas = pickle.load(pickle_file)
            except EOFError as e :
                print("[app.__init__()] : 불러올 pickle 데이터가 없음")
                self.datas = list()

        # 라우팅
        self.setup_route()
        
        # background_thread 시작함
        # TODO : start_background_task 작동하는지 확인
        background_thread = self.socketio.start_background_task(self.background_task)

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
        self.app.add_url_rule('/streaming/update_image', 'update_image', self.update_image, methods=['GET'])

    # TODO (기훈) : background_task 실제 서버 운영 스레드와 함께 정상 작동하도록 스레드 흐름 고치기
    def background_task(self):
        # 스마트팜으로부터 데이터를 읽어옴
        print("[app.background_task() 실행됨]")
        temperature = self.smartfarm.get_temperature()
        humidity = self.smartfarm.get_humidity()
        water_level = self.smartfarm.get_water_level() 
        first_light_state, second_light_state = self.smartfarm.get_light_state()
        heater_state = self.smartfarm.get_heater_state()
        pump_state = self.smartfarm.get_pump_state()

        name = ["humidity","temperature", "water_level", "first_light_state", "second_light_state", "heater_state", "pump_state"]
        a = list(map(convert_state, [humidity,temperature, water_level, first_light_state, second_light_state, heater_state, pump_state]))
        data_dict = dict(zip(name, a))

        # 만약 사용자가 인증되어있으면 give_data 이벤트 이름으로 data_json을 보냄
        # give_data 이벤트 이름으로 보낸 data_json 데이터는 stats.html에 적힌 자바스크립트에서 처리해 그래프에 추가할 것임
        if self.authenticated == True :
            with self.app.app_context() as context :
                data_json = jsonify(data_dict)
                self.socketio.emit('give_data', data_json)

        # self.datas에 저장할 data에는 timestamp 추가함
        now = datetime.now()
        now_str = now.strftime("%Y.%m.%d %H:%M:%S")
        data_dict['timestamp'] = now_str
        self.datas.append(data_dict)
    
        
        # TODO : time 종료
        # TODO : 30초 빼기 남은 측정시간만큼 기다리기

    def run(self):
        self.socketio.run(self.app)

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
        recent_datas = self.datas[-6:-1]    # 최근 6개 데이터
        inital_temperatures = [data['temperature'] for data in recent_datas]
        initial_water_levels = [data['water_level'] for data in recent_datas]
        initial_humidities = [data['humidity'] for data in recent_datas]
        # 맨 처음 stats.html을 서버에서 보내줄 때 초기 그래프에 표시될 데이터를 같이 주면
        # stats.html 자바스크립트 부분 초기 데이터 템플릿에 들어감
        return render_template('stats.html',
                               inital_temperatures=inital_temperatures,
                               initial_water_levels = initial_water_levels,
                               initial_humidities = initial_humidities)

    def control(self):
        #  TODO(태현) : 현재 설정값을 보여주는 text 만들어서 최초 Flask Jinja 템플릿 기능으로 현재 설정된 스마트팜 상태값을 보여주기
        return render_template('control.html')
    
    def set_temp(self):
        _temp = request.form['temp']
        print(f"[app.set_temp()] : _temp : {_temp} (type : {type(_temp)})")
        try :
            temp = float(_temp)
            self.smartfarm.set_min_temp(temp)
            return redirect(request.referrer)
        except ValueError as e :
            # TODO(태현) :Flask Jinja 템플릿 기능 이용해서 백엔드에서 입력 처리후 만약 허용되지 않은 입력(ex: 온도인데 '앙'같은 문자)이면 허용되지 않은 입력이라는 메시지 보내기
            pass
        
    def set_time_period(self):
        _on_time = request.form['turn_on_time']
        _off_time = request.form['turn_off_time']
        print(f"[app.set_time_period] : _on_time : {_on_time} ({type(_on_type)})")
        print(f"[app.set_time_period] : _off_time : {_off_time} ({type(_off_type)})")
            
        try :
            on_time = strptime(_on_time, '%Y.%m.%d %H:%M:%S')
            off_time = strptime(_off_time, '%Y.%m.%d %H:%M:%S')
            self.smartfarm.set_on_time(on_time)
            self.smartfarm.set_off_time(off_time)
        except ValueError as e :
            # TODO(태현) :Flask Jinja 템플릿 기능 이용해서 백엔드에서 입력 처리후 만약 허용되지 않은 입력(ex: 온도인데 '앙'같은 문자)이면 허용되지 않은 입력이라는 메시지 보내기
            pass

    # TODO (동우) : 버튼을 눌렀을때만 이미지를 얻어와 사용자의 웹사이트에 표시하는것이 아닌, 알아서 실시간으로 서버에서 웹사이트로 식물 사진을 보내줘 화면에 띄우도록 하기
    def streaming(self):
        return render_template('streaming.html')
        
    def update_image(self):
        print("[app.update_image 실행됨]")
        img_arr = self.smartfarm.get_image()
        img = Image.fromarray(img_arr, "RGB")
        image_filename = "last_taken_picture.jpeg"
        img.save(image_filename)
        return render_template('streaming.html', source='../' +image_filename)


if __name__ == '__main__':
    app_wrapper = FlaskAppWrapper(app, socketio)
    app_wrapper.run()
