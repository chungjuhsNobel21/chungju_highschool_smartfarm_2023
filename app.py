from flask import Flask, request, render_template, redirect
from threading import Lock
from flask_socketio import SocketIO, emit
from hardware import smartFarm_Device
from datetime import datetime

class FlaskAppWrapper():
    def __init__(self, app, farm, **configs):
        self.configs(**configs)
        self.app = Flask(__name__)
        self.smartfarm = smartFarm_Device()
        self.socketio = SocketIO(self.app)
        self.data = self.get_data_from_pickle()
        # socket 이벤트와 함수 매칭
        self.socketio.on_event()
        # endpoint: '/index' 같은거
        # endpoint_name : url_for 에 쓸 endpoint_name
        # handler 함수
        self.app.add_url_rule('/', 'index', self.index, methods=['GET'])
        self.app.add_url_rule('/auth', 'authenticate', self.authenticate, methods=['POST'])
        # TODO : start_background_task 작동하는지 확인
        # TODO : background_thread에서 context_manager 관련 문제 해결
        self.background_thread = self.socketio.start_background_task(self.background_task)

    # TODO : pickle에서 데이터 얻어오기
    def get_data_from_pickle():
        pass

    async def background_task(self):
        data = await self.smartfarm.get_data_from_smartfarm()
        # TODO : result 처리 및 저장 (동우)
        if self.authenticated == True :
            self.socketio.emit('give_data', data)

        # TODO : 전체 프로세스가 1분이 소요되도록 기다리기

    def index(self):
        return render_template('login.html')

    def authenticate(self):
        data = request.form
        print(data)

        id = request.form.get('id')
        pw = request.form.get('password')
        # 아이디와 비밀번호 확인
        if id == 'admin' and pw == 'chungju_h@1':
            return render_template('stat.html')
        
        else :
            # TODO : auth.html에서 아이디와 비밀번호를 다시 입력해주세요 창 띄우도록 템플릿 수정하여 반환하기
            return redirect(f'/stats/{id}')

    def stat(self):
        heater_state = self.get_heater_state()

smartfarm = smartFarm_Device()
flask_app  = Flask(__name__)
socketio = SocketIO(flask_app, cors_allowed_origins = '*')
app = FlaskAppWrapper(app = socketio, farm = smartfarm)


if __name__ == '__main__':
    app.run(debug=True)