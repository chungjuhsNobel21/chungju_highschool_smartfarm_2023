from flask import Flask, request, render_template, redirect, jsonify
from flask_socketio import SocketIO, emit
from hardware import smartFarm_Device
from datetime import datetime
import pickle

def convert_state(i):
    if i == "GPIO.HIGH":
        return "ON"
    elif i == "GPIO.LOW" :
        return "OFF"

class FlaskAppWrapper():
    def __init__(self, **configs):
        self.configs(**configs)
        self.app = Flask(__name__)
        self.smartfarm = smartFarm_Device()
        self.socketio = SocketIO(self.app)
        
        # 사용자 로그인 성공 여부
        self.authenticated = False


        # pickle로부터 데이터 가져오기
        # 읽기모드는 append, byte형 (pickle은 byte형으로 저장한다는게 중요함)
        ## self.datas의 구조
        # 개별 data의 구조는 {"timestamp" : "2023.08.08 07:11:09"와 같은 형태의 문자열, "temperature":float, "humidity":float, "water_level" : float
        # "first_light_state" : str ('ON'/'OFF'), "second_light_state" : str ('ON'/'OFF'), "heater_state" : str ('ON'/'OFF'), "pump_state" : str ('ON'/'OFF')}
        # self.datas는 위 개별 data들'을 시간순서대로 모아둔 list임
        with open('meas_data_pickle', 'ab') as pickle_file:
            self.datas = pickle.load(pickle_file)

        # 라우팅 설정
        self.setup_route()

        # socket 이벤트와 함수 매칭 예시
        # self.socketio.on_event()
        
        ## background_thread 시작함
        # TODO : start_background_task 작동하는지 확인
        self.background_thread = self.socketio.start_background_task(self.background_task)

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
        self.app.add_url_rule('control/set_temp', 'set_temp', self.set_temp, methods=['POST'])
        self.app.add_url_rule('control/set_time_period', 'set_time_period', self.set_time_period, methods=['POST'])

    def background_task(self):
        # 스마트팜으로부터 데이터를 읽어옴
        humidity, temperature = self.smartfarm.get_temp_and_humidity()
        water_level = self.smartfarm.get_water_level() 
        first_light_state, second_light_state = self.smartfarm.get_light_state()
        heater_state = self.smartfarm.get_heater_state()
        pump_state = self.smartfarm.get_pump_state()

        name = ["humidity","temperature", "water_level", "first_light_state", "second_light_state", "heater_state", "pump_state"]
        a = list(map(convert_state, [humidity,temperature, water_level, first_light_state, second_light_state, heater_state, pump_state]))
        data_dict = dict(zip(name, a))
        data_json = jsonify(data_dict)

        # self.datas에 저장할 data에는 timestamp 추가함
        now = datetime.now()
        now_str = now.strftime("%Y.%m.%d %H:%M:%S")
        data_dict['timestamp'] = now_str
        self.datas.append(data_dict)
    
        # 만약 사용자가 인증되어있으면 give_data 이벤트 이름으로 data_json을 보냄
        # give_data 이벤트 이름으로 보낸 data_json 데이터는 stats.html에 적힌 자바스크립트에서 처리해 그래프에 추가할 것임
        if self.authenticated == True :
            self.socketio.emit('give_data', data_json)

        # TODO : time 종료
        # TODO : 30초 빼기 남은 측정시간만큼 기다리기

    def index(self):
        return render_template('index.html')

    def authenticate(self):
        id = request.form.get('id')
        pw = request.form.get('password')

        # 아이디와 비밀번호 확인
        if id == 'admin' and pw == 'chungju_h@1':
            self.authenticated = True
            return render_template('stats.html')
        else :
            return render_template('stats.html', code=False)

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

    def set_temp():
        if request.method == 'POST':
            temp = request.form['temp']

        return render_template('hardware.py', min_temp= temp)


    
    def set_time_period():
        if request.method == 'POST':
            on_time = request.form['turn_on_time']
            off_time = request.form['turn_off_time']

        return render_template('hardware.py', turn_on_time = on_time, turn_off_time = off_time)    

app = FlaskAppWrapper()


if __name__ == '__main__':
    app.run(debug=True)
