import RPi.GPIO as GPIO
# pip install Adafruit_DHT로 DHT 온습도센서 사용 모듈을 설치
import Adafruit_DHT

import adafruit_mcp3xxx.mcp3008 as MCP
from adafruit_mcp3xxx.analog_in import AnalogIn
import time
import board
import busio
from datetime import datetime

# 핀 배치들을 변수로 저장해둠
pin_led_first_floor = 1
pin_led_second_floor = 2
pin_heater = 3
pin_pump = 4
pin_water_level_sensor = 5
pin_ph_sensor = 6
pin_dht_1 = 7
pin_dht_2 = 8
pin_dht_3 = 9
pin_dht_4 = 10

def check_state_integrity(state):
        '''state가 허용된 값인 GPIO.HIGH 혹은 GPIO.LOW 둘 중 하나의 값인지 무결성을 검증하는 함수'''
        if state != GPIO.OUT or state != GPIO.IN :
            raise Exception(f'state로 허용되지 않은 값 {state}가 주어졌습니다!')
        else :
            return

# 스마트팜 하드웨어와 소통하는 클래스를 정의
class smartFarm_Device:
    '''
    서버에서 스마트팜을 조작하기 위해 만든 스마트팜 제어 클래스
    핀 값들은 이 객체에 self.(핀번호) 변수로 저장된게 아니라 hardware.py 상단에 pin_어쩌구로 정의된거 갖다 씀.
    
    measure_어쩌구()로 어쩌구 값(온습도나 수위)을 측정해 self.어쩌구에 그 측정값들을 저장하고
    get_어쩌구()로 스마트팜의 상태 self.어쩌구를 서버로 얻어올 수 있고
    set_어쩌구(state)로 서버가 스마트팜의 사용자 설정값 self.user_set_어쩌구를 설정할 수 있고
    _어쩌구_update() 로 스마트팜의 상태 self.어쩌구에 맞게 장치를 켜거나 끔.
    '_'가 앞에 붙어있는 함수들 (_led_first_update 같은거)는 스마트팜 객체 밖에선 호출이 불가능함. 이는 보안을 위해 일부러 private 함수로 만듬
    set_어쩌구(state)로 스마트팜의 설정값을 설정할때 주어진 state가 GPIO.HIGH 혹은 GPIO.LOW같은
    GPIO.state 형인지 무결성 검사 check_state_integrity를 거침.

    '''
    def __init__(self, user_set_min_temp, user_set_on_time, user_set_off_time):
        '''
        클래스 초기화하며 서버에서 저장된 마지막 사용자설정상태를 받아 self.user_set_변수로 저장함
        - user_set_min_temp : 사용자가 설정한 최저온도
        - user_set_on_time : 사용자가 설정한 불 켜는 시각
        - user_set_off_time : 사용자가 설정한 불 끄는 시각
        '''
        # 사용자의 설정값
        self.user_set_min_temp = user_set_min_temp
        self.user_set_on_time = user_set_on_time
        self.user_set_off_time = user_set_off_time
        self.start_device()

    def start_device(self):
        '''GPIO 초기 설정을 진행하고 출력 핀을 기본모드로 설정'''
        # TEST : start_device 실제 작동 테스트
        # 라즈베리파이 핀맵 구성모드를 BCM으로 설정
        GPIO.setmode(GPIO.BCM)
        
        # 사용할 모든 핀들의 입출력 모드 설정
        GPIO.setup(pin_led_first_floor, GPIO.OUT)
        GPIO.setup(pin_led_second_floor, GPIO.OUT)
        GPIO.setup(pin_heater, GPIO.OUT)
        GPIO.setup(pin_ph_sensor, GPIO.IN)
        GPIO.setup(pin_pump, GPIO.OUT)
        GPIO.setup(pin_water_level_sensor, GPIO.IN)
        GPIO.setup(pin_dht_1, GPIO.IN)
        GPIO.setup(pin_dht_2, GPIO.IN)
        GPIO.setup(pin_dht_3, GPIO.IN)
        GPIO.setup(pin_dht_4, GPIO.IN)

        # 출력 핀들의 초기 출력모드 설정
        self.led_first_state = GPIO.HIGH
        self.led_second_state = GPIO.HIGH
        self.heater_state = GPIO.HIGH
        self.pump_state = GPIO.HIGH

        # 출력 핀들의 초기 출력모드에 따라서 실제 장치들을 켬
        self._heater_update()
        self._led_first_update()
        self._led_second_update()

        # TODO : dht 관련 문제들 해결 - 이 줄에서 센서 객체들이 인스턴스화가 안됨! ㅅㅂ
        # # 센서 4개의 객체들을 private하게 인스턴스화
        # self._dht_sensor_1 = Adafruit_DHT.DHT11(pin_dht_1)
        # self._dht_sensor_2 = Adafruit_DHT.DHT11(pin_dht_2)
        # self._dht_sensor_3 = Adafruit_DHT.DHT11(pin_dht_3)
        # self._dht_sensor_4 = Adafruit_DHT.DHT11(pin_dht_4)

        # 측정에 사용할 센서들을 모아둔 배열
        # self._dht_sensors = [self._dht_sensor_1, self._dht_sensor_2, self._dht_sensor_3, self._dht_sensor_4]
    
        # TODO : 아날로그 입력 CS 설정 안되는 문제 해결
        # # MCP3008 모듈의 SPI 통신 설정 - 클럭(11)과 MISO(9), MOSI(10) 단자 모두 보드에 정해진 것을 따름
        # spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=board.MOSI)
        # # MCP3008 객체 생성
        # mcp = MCP.MCP3008(spi)
        # # 아날로그 입력 채널 설정 (0번 핀을 사용하려면 CH0 사용)
        # self._analog_channel = AnalogIn(mcp, MCP.P0)



    def off_device(self):
        '''펌프를 끄고 장비를 정지함'''
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

        # # 사용했던 DHT 센서 객체들 삭제
        # del(self._dht_sensor_1)
        # del(self._dht_sensor_2)
        # del(self._dht_sensor_3)
        # del(self._dht_sensor_4)

        GPIO.cleanup()  # GPIO 초기화

    def adjust(self):

        # 온도 조절
        if self.temperature < self.set_min_temperature:
            self._heater_update(GPIO.HIGH)
        else:
            self._heater_update(GPIO.LOW)

        now = datetime.now().time()

        if self.on_time <= now < self.off_time:
            self.led_first_state = GPIO.HIGH
            self.led_first_state = GPIO.LOW
            self._led_first_update()
            self._led_second_update()
        else:
            self.led_first_state = GPIO.HIGH
            self.led_first_state = GPIO.LOW
            self._led_first_update()
            self._led_second_update()




    def measure_temp_and_humidity(self)->None :
        '''
        온도 및 습도 측정해 self.temperature, self.humidity에 저장하는 함수
        '''
        # TEST : measure_temp_and_humidity 실제 작동 테스트
        # TEST : 온습도 측정에서 비동기가 잘 되는지 확인하기
        humidities = list()
        temperatures = list()
        count = 0
        for i, sensor in enumerate(self._dht_sensors):
            # 측정 시도
            try :
                # 1번 dht sensor의 핀번호가 7번으로 시작하기 때문에 핀번호를 7+i로 함
                humid, temperature = Adafruit_DHT.read_retry(self._dht_sensors[i], 7+i)
                humidities[i] = humid
                temperatures[i] = temperature
                count += 1
            # 측정 실패시
            except RuntimeError as e:
                print(e.args[0])
        
        # 측정값이 하나도 없으면
        if count == 0:
            raise Exception('온습도센서로 측정한 값이 없습니다!')
                
        avg_humid = sum(humidities) / count
        avg_temp = sum(temperatures) / count
        
        self.humidity = avg_humid
        self.temperature = avg_temp

    def measure_water_level(self)->None :
        '''3층 물통 수위 측정해 self.water_level 값을 갱신하는 함수'''
        # TODO : measure_water_level 아날로그 변환 식 제대로 작성하기
        raw_value = self._analog_channel_water_level.value
        voltage = raw_value / 65535.0 * 5.0
        water_level = voltage/5.0 #상수값은 센서 길이따라 변동
        
        self.water_level = water_level


    def set_pump_state(self, state) :
        '''
        펌프의 상태 self.pump_state를 지정하고 그에 맞게 펌프를 켜거나 끄는 함수
        - state : 설정할 펌프의 상태 (GPIO.HIGH/GPIO.LOW)
         * 허용되지 않은 값이 state로 입력될 경우 예외를 raise함
        -> return None
        '''
        
        # TEST : set_pump_state 실제 작동 테스트

        # 인자로 주어진 state의 무결성 검증 - 결함 있으면 에러 raise하여 backend단에서 처리하게 함.
        try :
            self.check_state_integrity(state)
        except Exception as e :
            raise e
    
        print(f"[set_pump_state] : 펌프 상태를 {state}로 설정합니다")
        self.pump_state = state
        self._pump_update()        

    def set_light_state(self, state:list) :
        '''
        전등의 self.pump_state를 지정하고 그에 맞게 펌프를 켜거나 끄는 함수
        - state : 설정할 펌프의 상태 (GPIO.HIGH/GPIO.LOW)
         * 허용되지 않은 값이 state로 입력될 경우 예외를 raise함
        -> return None
        '''

        # TEST : set_light_state 실제 작동 테스트
        # state 값 무결성 검증 - 실패시 에러 raise하여 backend에서 처리할 수 있게 함.
        try : 
            self.check_state_integrity(state[0])
        except Exception as e:
            raise e
        
        try : 
            self.check_state_integrity(state[1])
        except Exception as e:
            raise e
        
        # 객체의 led_state 업데이트
        self.led_first_state = state[0]
        self.led_second_state = state[1]
        print(f"[set_led_state] : 1층 LED 상태를 {self.led_first_state}로 설정합니다.")
        print(f"[set_led_state] : 2층 LED 상태를 {self.led_second_state}로 설정합니다.")
        # 실제 스마트팜의 led 상태 업데이트해 켜거나 끔
        self._led_first_update()
        self._led_second_update()

    def set_heater_state(self, state) :
        '''전체 히터의 상태를 지정하는 함수 (GPIO.HIGH/GPIO.LOW)'''

        # TEST : set_heater_state 실제 작동 테스트
        # 인자로 주어진 state의 무결성 검증 - 결함 있으면 에러 raise하여 backend단에서 처리하게 함.
        try :
            self.check_state_integrity(state)
        except Exception as e :
            raise e
    
        print(f"[set_heater_state] : 히터 상태를 {state}로 설정합니다")
        self.heater_state = state
        self._heater_update()
      
    def set_min_temp(self, user_set_min_temperature):
        self.user_set_min_temperature = user_set_min_temperature
  
    def set_on_time(self, user_set_on_time):
        self.user_set_on_time = user_set_on_time
  
    def set_off_time(self, user_set_off_time):
        self.user_set_off_time = user_set_off_time


    def get_pump_state(self):
        '''펌프 작동 상태 반환하는 함수 (GPIO.HIGH 혹은 GPIO.LOW)'''
        # TEST : get_pump_state 실제 작동 테스트
        return self.pump_state


    def get_water_level(self) -> float:
        return self.water_level


    def get_light_state(self)->list :
        '''1층과 2층 LED 전원 상태를 얻어오는 함수 [GPIO.HIGH/GPIO.LOW, GPIO.HIGH/GPIO.LOW]'''
        # TEST : get_light_state 실제 작동 테스트
        return [self.led_first_state, self.led_second_state]

    
    def get_heater_state(self) :
        '''히터의 상태를 반환하는 함수 (GPIO.HIGH 혹은 GPIO.LOW)'''
        # TEST : get_heater_state 실제 작동 테스트
        return self.heater_state

  
    def get_image(self):
        # 사진(png) 찍고 저장?
        smf_camera = picamera.Picamera()
        photo_width = 600
        photo_height = 600

        smf_camera.start_preview()
        time.sleep(2)

        smf_photo_arr = np.empty((photo_height,photo_width), dtype =np.unit8)
        smf_camera.capture(smf_photo_arr,format='rgb')

        smf_camera.stop_preview()
        smf_camera.close()  
        
        return smf_photo_arr


    def _pump_update(self):
        '''현재 self.pump_state에 맞게 펌프를 끄거나 켜는 함수'''
        # TEST : _pump_update 실제 작동 테스트
        print(f"[_pump_update] : 펌프를 {self.pump_state}로 켭니다/끕니다.")
        GPIO.output(pin_pump, self.pump_state)

    def _led_first_update(self):
        # TEST : _led_first_update 실제 작동 테스트
        print(f"[_led_first_update] : 1층 LED를 {self.led_first_state}로 켭니다/끕니다.")
        GPIO.output(self.pin_led_first_floor, self.led_first_state)
        
    def _led_second_update(self):
        # TEST : _led_first_update 실제 작동 테스트
        print(f"[_led_second_update] : 2층 LED를 {self.led_second_state}로 켭니다/끕니다.")
        GPIO.output(self.pin_led_second_floor, self.led_second_state)        