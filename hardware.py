import RPi.GPIO as GPIO
from socketIO_client import SocketIO, LoggingNamespace
# pip install Adafruit_DHT로 DHT 온습도센서 사용 모듈을 설치
import Adafruit_DHT
import threading
import spidev
from time import sleep
from datetime import datetime, time
import picamera
from PIL import Image
from io import BytesIO
import board
import base64

# 핀 배치들을 변수로 저장해둠
pin_led_first_floor = 23
pin_led_second_floor = 19                                                                                                     
pin_heater = 17
pin_pump = 16
pin_dhts = [26, 4, 18, 21]



# 사용자 설정값이 주어지지 않았을 경우 사용할 기본값
DEFAULT_MIN_TEMP = 18
DEFAULT_ON_TIME = time(hour=5)
DEFAULT_OFF_TIME = time(hour=19)

# 사용할 서버 앱 초기화
app = Flask(__name__)
# TODO : IP주소와 포트번호 배포용으로 바꾸기
socketio = SocketIO('localhost', 8000, LoggingNamespace)

# 스마트팜 하드웨어와 소통하는 클래스를 정의
class SmartFarmDevice:
    """
    스마트팜 서버 클래스
    핀 값들은 이 객체에 self.(핀번호) 변수로 저장된게 아니라 hardware.py 상단에 pin_어쩌구로 정의된거 갖다 씀.

    measure_어쩌구()로 어쩌구 값(온습도나 수위)을 측정해 self.어쩌구에 그 측정값들을 저장하고
    get_어쩌구()로 스마트팜의 상태 self.어쩌구를 서버로 얻어올 수 있고
    set_어쩌구(state)로 서버가 스마트팜의 사용자 설정값 self.user_set_어쩌구를 설정할 수 있고
    _어쩌구_update() 로 스마트팜의 상태 self.어쩌구에 맞게 장치를 켜거나 끔.
    '_'가 앞에 붙어있는 함수들 (_led_first_update 같은거)는 스마트팜 객체 밖에선 호출이 불가능함. 이는 보안을 위해 일부러 private 함수로 만듬
    set_어쩌구(state)로 스마트팜의 설정값을 설정할때 주어진 state가 GPIO.HIGH 혹은 GPIO.LOW같은
    GPIO.state 형인지 무결성 검사 check_state_integrity를 거침.

    """

    def __init__(self, user_set_min_temp=None, user_set_on_time: time = None, user_set_off_time: time = None,):
        """
        클래스 초기화하며 서버에 저장된 마지막 사용자 설정상태를 인자로 받아 self.user_set_(변수)로 저장함.
        마지막 사용자 설정상태가 주어지지 않으면 자동으로 최저온도 18도, 켜는시각 05시 00분, 끄는 시각 19시 00분으로 설정됨.
        - user_set_min_temp(float): 사용자가 설정한 최저온도
        - user_set_on_time(time) : 사용자가 설정한 불 켜는 시각
        - user_set_off_time(time) : 사용자가 설정한 불 끄는 시각
        """
        self.image_send_count = 0

        # 측정값들 변수 정의
        self.temperature = 15
        self.humidity = 50
        self.water_level = 2

        # 각종 액추에이터들의 출력 상태 변수 정의 - 어차피 아래 adjust 함수 실행하면서 바뀔 것임
        self.pump_state = GPIO.HIGH
        self.led_first_state = GPIO.HIGH
        self.led_second_state = GPIO.HIGH
        self.heater_state = GPIO.LOW

        # spi 기본 설정
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 1000000

        #  TODO: 카메라 관련 주석 풀기
        #self.camera = picamera.PiCamera()
        self.stream = BytesIO()

        # 사용자의 설정값을 지정함
        self.min_temp = user_set_min_temp
        self.on_time: time = user_set_on_time  # user_set_on_time은 app.py 에서 전달받은 설정값은 %H:%M (즉, 시:분) 형식의 datetime 객체임
        self.off_time: time = user_set_off_time
        if self.min_temp is None:
            print(f"[hardware] : 최저 온도 설정값이 주어지지 않아 기본값 {DEFAULT_MIN_TEMP}로 설정합니다!")
            self.min_temp = DEFAULT_MIN_TEMP
        if self.on_time is None:
            print(f"[hardware] : 불을 켜는 시각이 주어지지 않아 기본값 {DEFAULT_ON_TIME}로 설정합니다!")
            self.on_time = DEFAULT_ON_TIME
        if self.off_time is None:
            print(f"[hardware] : 불을 끄는 시각이 주어지지 않아 기본값 {DEFAULT_OFF_TIME}로 설정합니다!")
            self.off_time = DEFAULT_OFF_TIME

        # GPIO 초기설정
        self.setup_gpio()

        # 스마트팜이 켜지고 초기 측정값을 얻어옴
        # self.measure_temp_and_humidity()
        # self.measure_water_level()

        # 사용자 설정값에 맞게 스마트팜 전등과 히터를 켜거나 끔
        self.adjust()

        # 라우팅 및 백그라운드 스레드 설정 등 함
        self.setup_server()

    def setup_server(self):
        # 환경 조절 스레드
        self.adjust_timer = threading.Timer(2, self.adjust)
        # 주기적으로 서버로부터 유저 설정 얻어오는 스레드
        self.get_user_setting_timer = threading.Timer(5, self.get_user_setting)
        # 측정 및 emit 스레드
        self.measure_and_emit_timer = threading.Timer(30, self.measure_and_emit)
        # 이미지 촬영 후 emit 스레드
        self.update_image_timer = threading.Timer(6, self.update_image)

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

    # TEST : 스마트팜 adjust 함수 테스트
    def adjust(self):
        socketio.emit('user_setting_request', None, self.on_user_setting_data_received)
        socketio.wait_for_callback(seconds=1)

    # TEST : 스마트팜 on_user_setting_data_received 함수 테스트     
    def on_user_setting_data_received(self, data):
        print("[hardware] : on_user_setting_data_received 함수 실행됨")
        print(data)

    # TEST : 스마트팜 measure_and_emit 함수 테스트
    def measure_and_emit(self):
        print("[hardware.measure_and_emit() 실행됨]")
        start_time = time.time()
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
        states = list(map(self.convert_state, [self.led_first_state, self.led_second_state, self.heater_state, self.pump_state]))
        data_dict = dict(zip(name, [now_str, self.humidity, self.temperature, self.water_level] + states))  # 만든 결과 dict
        # 이벤트 이름 'give_data'로 데이터 data_dict를 emit -> stats.html에 적힌 자바스크립트에서 처리해 그래프에 추가할 것
        socketio.emit("sensor_data", data_dict)  # socketio.emit 함수를 사용할때는 jsonify()를 사용하지 말고 그냥 딕셔너리 형태의 데이터를 주어야 함!
        # 참고 : https://stackoverflow.com/questions/75004494/typeerror-object-of-type-response-is-not-json-serializable-2


    # TEST : 스마트팜 update_image_periodically 함수 테스트
    def update_image(self):
        """
        6초에 한번씩 이미지를 얻어 'give_image'란 이벤트 이름으로 이미지를 byte형으로 서버에 emit하는 스레드용 함수.
        30초에 한번씩은 스마트팜에서 얻은 byte형 이미지를 로컬에 측정시각을 파일 이름으로 하여 jpeg로 저장함.
        """
        print(f"[update_image 실행됨] {self.image_send_count}")
        # 사진을 파일로 저장하는 주기는 30초로하고, 30초 이전에는 저장 없이 스트림에서 byte64로 이미지만 가져옴
        # CLEANUP : 이미지를 파일로 저장하는 기능은 스마트팜이 아니라 서버에서 구현하는게 맞을듯. 스마트팜의 get_image에 save_to_file을 인자로 주어 그에 맞게 스마트팜에서 이미지를 저장하거나 저장하지 않도록 하는 것이 아니라,
        #           스마트팜은 단순히 이미지를 찍어 byte로 리턴하고, 저장은 서버의 update_image 함수에서 하자
        
        if self.image_send_count % 5 == 0:
            byte_image = self.smartfarm.get_image(save_to_file=True)
            self.image_send_count = 0
        else:
            byte_image = self.smartfarm.get_image(save_to_file=False)
            self.imgae_send_count += 1
        socketio.emit("give_image_to_server", {"byte_image": byte_image})

    def check_state_integrity(self, state):
        """state가 허용된 값인 GPIO.HIGH 혹은 GPIO.LOW 둘 중 하나의 값인지 무결성을 검증하는 함수"""
        if state != GPIO.HIGH and state != GPIO.LOW:
            raise Exception(f"state로 허용되지 않은 값 {state}가 주어졌습니다!")
        else:
            return

    def setup_gpio(self):
        """GPIO 초기 설정을 진행"""
        # TEST : start_device 실제 작동 테스트
        # 라즈베리파이 핀맵 구성모드를 BCM으로 설정
        GPIO.setmode(GPIO.BCM)

        # 사용할 모든 핀들의 입출력 모드 설정
        GPIO.setup(pin_led_first_floor, GPIO.OUT)
        GPIO.setup(pin_led_second_floor, GPIO.OUT)
        GPIO.setup(pin_heater, GPIO.OUT)
        GPIO.setup(pin_pump, GPIO.OUT)

    def off_device(self):
        """펌프를 끄고 장비를 정지함"""
        # TEST : off_device 실제 작동 테스트

        # 출력핀들의 모드를 LOW로 설정
        self.led_first_state = GPIO.LOW
        self.led_second_state = GPIO.LOW
        self.heater_state = GPIO.LOW
        self.pump_state = GPIO.LOW

        # LOW 출력핀 모드대로 장비에 전원을 끊음
        self._led_first_update()
        self._led_second_update()
        self._heater_update()
        self._pump_update()

        GPIO.cleanup()  # GPIO 초기화

    def adjust(self):
        """
        측정된 센서값과 사용자 설정값을 비교하여 전등과 히터를 켜거나 끄는 함수.
        """
        # 히터 조절하기 - Tested
        if self.temperature < self.min_temp and self.heater_state == GPIO.LOW:
            self.heater_state = GPIO.HIGH
            self._heater_update()
        elif self.temperature > (self.min_temp + 2) and self.heater_state == GPIO.HIGH:
            self.heater_state = GPIO.LOW
            self._heater_update()

        # datetime.now()로 오늘의 날짜와 시각을 담은 datetime 객체를 얻고 time()함수로 시간만을 표현하는 time 객체로 변환함.
        # self.on_time 과 self.off_time이 모두 time 객체이기 때문에 비교를 위해서 필요함.
        now = datetime.now().time()

        # 켜는시각이 끄는시각보다 앞서면 - Tested
        if self.on_time < self.off_time:
            if self.on_time <= now and now < self.off_time:  # 켜야할 시각이 되면
                if (
                    self.led_first_state == GPIO.LOW
                    and self.led_second_state == GPIO.LOW
                ):  # 불이 꺼져있으면 켬
                    self.led_first_state = GPIO.HIGH
                    self.led_second_state = GPIO.HIGH
                    self._led_first_update()
                    self._led_second_update()

            else:  # 꺼야할 시각이 되면
                if (
                    self.led_first_state == GPIO.HIGH
                    and self.led_second_state == GPIO.HIGH
                ):  # 불이 켜져있으면 끔
                    self.led_first_state = GPIO.LOW
                    self.led_second_state = GPIO.LOW
                    self._led_first_update()
                    self._led_second_update()

        # 끄는시각이 켜는시각보다 앞서면 - Tested
        elif self.on_time > self.off_time:
            if now < self.off_time or now >= self.on_time:  # 켜야할 시각이 되면
                if (
                    self.led_first_state == GPIO.LOW
                    and self.led_second_state == GPIO.LOW
                ):  # 불이 꺼져있으면 켬
                    self.led_first_state = GPIO.HIGH
                    self.led_second_state = GPIO.HIGH
                    self._led_first_update()
                    self._led_second_update()

            else:  # 꺼야할 시각이 되면
                if (
                    self.led_first_state == GPIO.HIGH
                    and self.led_second_state == GPIO.HIGH
                ):  # 불이 켜져있으면 끔
                    self.led_first_state = GPIO.LOW
                    self.led_second_state = GPIO.LOW
                    self._led_first_update()
                    self._led_second_update()

    def measure_temp_and_humidity(self) -> None:
        """
        온도 및 습도 측정해 self.temperature, self.humidity에 저장하는 함수.
        """
        print("[hardware.measure_temp_and_humidity() 실행됨]")
        humidities = [0, 0, 0, 0]
        temperatures = [0, 0, 0, 0]
        humid_count = 0
        temp_count = 0
        sensor_type = Adafruit_DHT.DHT11

        # 측정을 위한 Worker 스레드 클래스
        class MeasureWorker(threading.Thread):
            def __init__(self, pin):
                super().__init__()
                self.temp = None
                self.humid = None
                self.pin = pin

            def run(self):
                self.measure()

            def measure(self):
                self.humid, self.temp = Adafruit_DHT.read_retry(
                    sensor_type, self.pin, retries=14
                )
                print(
                    f"    [worker({self.pin})] humid : {self.humid}, temp : {self.temp}"
                )

        # 측정용 스레드 만들고 동시에 실행하여 측정값을 얻음
        threads = []
        for i in range(4):
            thread = MeasureWorker(pin_dhts[i])
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()  # 만든 스레드들의 종료시각이 일치하도록 join함

        for i in range(4):
            if threads[i].humid is not None:
                humidities[i] = threads[i].humid
                humid_count += 1
            if threads[i].temp is not None:
                temperatures[i] = threads[i].temp
                temp_count += 1

        # 측정값이 하나도 없으면
        if humid_count == 0:
            print(f"온습도센서로 측정한 습도값이 없습니다! - 이전에 저장된 습도값을 반환합니다 : {self.humidity}")
        else:
            self.humidity = sum(humidities) / humid_count
            print(
                f"    [hardware.measure_temp_and_humidity()] 측정된 습도값 : {self.humidity}"
            )

        if temp_count == 0:
            print(f"온습도센서로 측정한 온도값이 없습니다! - 이전에 저장된 온도값을 반환합니다 : {self.temperature}")
        else:
            self.temperature = sum(temperatures) / temp_count
            print(
                f"    [hardware.measure_temp_and_humidity()] 측정된 온도값 : {self.temperature}"
            )

    def measure_water_level(self) -> None:
        """3층 물통 수위 측정해 self.water_level 값을 갱신하는 함수"""
        print("[hardware.measure_water_level() 실행됨]")
        adc = self.spi.xfer2([1, (8 + 0) << 4, 0])
        adc_out = ((adc[1] & 3) << 8) + adc[2]
        a_volt = 3.3 * adc_out / 1024
        print(f"adc_out : {adc_out}")
        self.water_level = self.adc_to_water_level(a_volt)

    def adc_to_water_level(self, a_volt):
        """수위센서에서 읽은 analog volt값을 수위 cm으로 환산하는 함수"""
        # adc_value 리턴한건 그냥 데이터 반환이 필요해서 한거임
        return a_volt
        # TODO(정수) : 수위센서 adc -> cm 환산 함수 실험 및 실측을 통해 근사식 작성하기

    def set_pump_state(self, state):
        """
        펌프의 상태 self.pump_state를 지정하고 그에 맞게 펌프를 켜거나 끄는 함수
        - state : 설정할 펌프의 상태 (GPIO.HIGH/GPIO.LOW)
         * 허용되지 않은 값이 state로 입력될 경우 예외를 raise함
        -> return None
        """
        # 인자로 주어진 state의 무결성 검증 - 결함 있으면 에러 raise하여 backend단에서 처리하게 함.
        try:
            self.check_state_integrity(state)
        except Exception as e:
            raise e

        print(f"[set_pump_state] : 펌프 상태를 {state}로 설정합니다")
        self.pump_state = state
        self._pump_update()

    def set_led_first_state(self, state):
        """
        1층 전구 상태 self.led_first_state 지정하고 그에 맞게 전구를 켜거나 끄는 함수
        - state : 설정할 펌프의 상태 (GPIO.HIGH/GPIO.LOW)
         * 허용되지 않은 값이 state로 입력될 경우 예외를 raise함
        -> return None
        """
        # state 값 무결성 검증 - 실패시 에러 raise하여 backend에서 처리할 수 있게 함.
        try:
            self.check_state_integrity(state)
        except Exception as e:
            raise e

        self.led_first_state = state
        print(f"[set_led_first_state] : 1층 LED 상태를 {self.led_first_state}로 설정합니다.")
        self._led_first_update()  # 실제 led 상태 업데이트

    def set_led_second_state(self, state):
        """
        2층 전구 상태 self.led_second_state 지정하고 그에 맞게 전구를 켜거나 끄는 함수
        - state : 설정할 펌프의 상태 (GPIO.HIGH/GPIO.LOW)
         * 허용되지 않은 값이 state로 입력될 경우 예외를 raise함
        -> return None
        """
        # state 값 무결성 검증 - 실패시 에러 raise하여 backend에서 처리할 수 있게 함.
        try:
            self.check_state_integrity(state)
        except Exception as e:
            raise e

        self.led_second_state = state
        print(f"[set_led_second_state] : 2층 LED 상태를 {self.led_second_state}로 설정합니다.")
        self._led_second_update()  # 실제 led 상태 업데이트

    def set_heater_state(self, state):
        """전체 히터의 상태를 지정하는 함수 (GPIO.HIGH/GPIO.LOW)"""
        # 인자로 주어진 state의 무결성 검증 - 결함 있으면 에러 raise하여 backend단에서 처리하게 함.
        try:
            self.check_state_integrity(state)
        except Exception as e:
            raise e

        print(f"[set_heater_state] : 히터 상태를 {state}로 설정합니다")
        self.heater_state = state
        self._heater_update()

    def set_min_temp(self, _min_temp):
        print(f"[hardware.set_min_temp] : 설정 최저 온도를 {_min_temp}로 설정합니다")
        self.min_temp = _min_temp

    def set_on_time(self, _on_time: datetime):
        print(f"[hardware.set_on_time] : 전등을 킬 시각을 {_on_time}로 설정합니다")
        self.on_time = _on_time

    def set_off_time(self, _off_time: datetime):
        print(f"[hardware.set_off_time] : 전등을 끌 시각을 {_off_time}로 설정합니다")
        self.off_time = _off_time

    def get_temperature(self):
        return self.temperature

    def get_humidity(self):
        return self.humidity

    def get_pump_state(self):
        """펌프 작동 상태 반환하는 함수 (GPIO.HIGH 혹은 GPIO.LOW)"""
        return self.pump_state

    def get_water_level(self) -> float:
        return self.water_level

    def get_led_first_state(self):
        """1층 LED 전원 상태를 얻어오는 함수 (GPIO.HIGH/GPIO.LOW)"""
        return self.led_first_state

    def get_led_second_state(self):
        """2층 LED 전원 상태를 얻어오는 함수 (GPIO.HIGH/GPIO.LOW)"""
        return self.led_second_state

    def get_heater_state(self):
        """히터의 상태를 반환하는 함수 (GPIO.HIGH 혹은 GPIO.LOW)"""
        return self.heater_state

    def get_image(self, save_to_file=False):
        #        '''
        #        사진을 찍어 byte로 반환함.
        #        -save_to_file : True로 설정되면 f"./captured_images/{datetime.now().strftime('%Y.%m.%d_%H:%M:%S')}.jpeg"로 파일을 저장
        print(f"[hardware.get_image({save_to_file}) 실행됨]")
        photo_width = 600
        photo_height = 600
        #self.camera.capture(self.stream, format='jpeg')
        #self.stream.seek(0)
        encoded_image = self.stream.getvalue()
        #self.stream.seek(0)
        if save_to_file == True :
            with Image.open(self.stream) as img :
                image_path = './captured_images/'
                image_filename = f"{datetime.now().strftime('%Y.%m.%d_%H:%M:%S')}.jpeg"
                img.save(image_path + image_filename)
            #self.stream.seek(0)
 
        return encoded_image

    def _pump_update(self):
        """현재 self.pump_state에 맞게 펌프를 끄거나 켜는 함수"""
        print(f"[_pump_update] : 펌프를 {self.pump_state}로 켭니다/끕니다.")
        GPIO.output(pin_pump, self.pump_state)

    def _heater_update(self):
        print(f"[_heater_update] : 히터를 {self.heater_state}로 켭니다/끕니다.")
        GPIO.output(pin_heater, self.heater_state)

    def _led_first_update(self):
        print(f"[_led_first_update] : 1층 LED를 {self.led_first_state}로 켭니다/끕니다.")
        GPIO.output(pin_led_first_floor, self.led_first_state)

    def _led_second_update(self):
        print(f"[_led_second_update] : 2층 LED를 {self.led_second_state}로 켭니다/끕니다.")
        GPIO.output(pin_led_second_floor, self.led_second_state)


if __name__ == "__main__":
    d = SmartFarmDevice()
