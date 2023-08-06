import RPi.GPIO as GPIO
# pip install Adafruit_DHT로 DHT 온습도센서 사용 모듈을 설치
import Adafruit_DHT

import adafruit_mcp3xxx.mcp3008 as MCP
from adafruit_mcp3xxx.analog_in import AnalogIn
import time
import board
import busio
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



# 스마트팜 하드웨어와 소통하는 클래스를 정의
class smartFarm_Device:

    def __init__(self):
        '''클래스 초기화'''
        self.water_level:int
        self.ph_level:int
        self.start_device()
        

    def check_state_integrity(state):
        '''state가 허용된 값인 GPIO.HIGH 혹은 GPIO.LOW 둘 중 하나의 값인지 무결성을 검증하는 함수'''
        if state != GPIO.OUT or state != GPIO.IN :
            raise Exception(f'state로 허용되지 않은 값 {state}가 주어졌습니다!')
        else :
            return

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

        # 출력 핀들의 기본 출력모드 설정
        self.led_first_state = GPIO.HIGH
        self.led_second_state = GPIO.HIGH
        self.heater_state = GPIO.HIGH
        self.pump_state = GPIO.HIGH
        self._heater_on()
        self._led_first_on()
        self._led_second_on()

        # 센서 4개의 객체들을 private하게 인스턴스화
        self._dht_sensor_1 = Adafruit_DHT.DHT11(pin_dht_1)
        self._dht_sensor_2 = Adafruit_DHT.DHT11(pin_dht_2)
        self._dht_sensor_3 = Adafruit_DHT.DHT11(pin_dht_3)
        self._dht_sensor_4 = Adafruit_DHT.DHT11(pin_dht_4)

        # 측정에 사용할 센서들을 모아둔 배열
        self._dht_sensors = [self._dht_sensor_1, self._dht_sensor_2, self._dht_sensor_3, self._dht_sensor_4]
    
        # MCP3008 모듈의 SPI 통신 설정 - 클럭(11)과 MISO(9), MOSI(10) 단자 모두 보드에 정해진 것을 따름
        spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=board.MOSI)
        # MCP3008 객체 생성
        mcp = MCP.MCP3008(spi)
        # TODO : 아날로그 입력 채널 핀 설정?? 0번핀이 뭔데
        # 아날로그 입력 채널 설정 (0번 핀을 사용하려면 CH0 사용)
        self._analog_channel = AnalogIn(mcp, MCP.P0)
        self._analog_channel_water_level = AnalogIn(mcp, MCP.P1)



    def off_device(self):
        '''펌프를 끄고 장비를 정지함'''
        # TEST : off_device 실제 작동 테스트

        # 출력핀들의 모드를 LOW로 설정
        self.led_first_state = GPIO.LOW
        self.led_second_state = GPIO.LOW
        self.heater_state = GPIO.LOW
        self.pump_state = GPIO.LOW

        # LOW 출력핀 모드대로 장비에 전원을 끊음
        self._led_first_update(self.led_first_state)
        self._led_second_update(self.led_second_state)
        self._heater_update(self.heater_state)
        self._pump_update(self.pump_state)

        # 사용했던 DHT 센서 객체들 삭제
        del(self._dht_sensor_1)
        del(self._dht_sensor_2)
        del(self._dht_sensor_3)
        del(self._dht_sensor_4)

        GPIO.cleanup()  # GPIO 초기화


    def get_temp_and_humidity(self)->list[float, float] :
        '''
        온도 및 습도 측정해 반환하는 함수
        -> [avg_humidity, avg_temperature]
        '''
        # TEST : get_temp_and_humidity 실제 작동 테스트
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
        return [avg_humid, avg_temp]

    def get_ph(self)->float :
        '''ph 측정해 반환하는 함수'''

        # 여러 번 측정하여 평균값을 계산합니다.
        num_samples = 10
        total_ph = 0.0
        for _ in range(num_samples):
            # 아날로그 값을 읽어옵니다.
            raw_value = self._analog_channel.value
            # ADC 값을 전압 값으로 변환합니다.
            voltage = raw_value / 65535.0 * 5.0

            # TODO : 실제 pH값 계산식 적용
            # pH 값을 계산합니다. (변환식은 pH 측정 센서에 따라 다를 수 있습니다.)
            # 해당 변환식은 예시일 뿐, 실제 센서의 데이터시트를 참고해야 합니다.
            ph = 7 - (voltage - 2.5) * 3
            total_ph += ph
            # 측정 사이에 잠시 대기합니다.
            time.sleep(0.1)

        # 평균 pH 값을 계산합니다.
        avg_ph = total_ph / num_samples

        return avg_ph

    def set_pump_state(self, state) :
        '''펌프의 상태를 지정하는 함수 (GPIO.HIGH/GPIO.LOW)'''
        # TEST : set_pump_state 실제 작동 테스트
        # 인자로 주어진 state의 무결성 검증 - 결함 있으면 에러 raise하여 backend단에서 처리하게 함.
        try :
            self.check_state_integrity(state)
        except Exception as e :
            raise e
    
        print(f"[set_pump_state] : 펌프 상태를 {state}로 설정합니다")
        self.pump_state = state
        self._pump_update(self.pump_state)

    def get_pump_state(self):
        '''펌프 작동 상태 반환하는 함수 (GPIO.HIGH 혹은 GPIO.LOW)'''
        # TEST : get_pump_state 실제 작동 테스트
        return self.pump_state

    def _pump_update(self, state):
        '''주어진 state에 맞게 펌프를 끄거나 켜는 함수'''
        # TEST : _pump_update 실제 작동 테스트
        print(f"[_pump_update] : 펌프를 {state}로 켭니다/끕니다.")
        GPIO.output(self.pin_pump, state)
    
    def get_water_level(self)->float :
        '''3층 물통 수위 측정해 반환하는 함수'''
        raw_value = self._analog_channel_water_level.value
        voltage = raw_value / 65535.0 * 5.0
        water_level = voltage/5.0 #상수값은 센서 길이따라 변동
        
        return water_level
        

    def set_light_state(self, state:list) :
        '''
        1층 혹은 2층 LED 전원 상태를 지정하는 함수
        - state(list) : LED 전원 상태 리스트 [1층, 2층] (GPIO.HIGH 혹은 GPIO.LOW)
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
        self._led_first_update(self.led_first_state)
        self._led_second_update(self.led_second_state)


    def get_light_state(self)->list :
        '''1층과 2층 LED 전원 상태를 얻어오는 함수 [GPIO.HIGH/GPIO.LOW, GPIO.HIGH/GPIO.LOW]'''
        # TEST : get_light_state 실제 작동 테스트
        return [self.led_first_state, self.led_second_state]

    def _led_first_update(self, state):
        # TEST : _led_first_update 실제 작동 테스트
        print(f"[_led_first_update] : 1층 LED를 {state}로 켭니다/끕니다.")
        GPIO.output(self.pin_led_first_floor, state)
        
    def _led_second_update(self, state):
        # TEST : _led_first_update 실제 작동 테스트
        print(f"[_led_second_update] : 2층 LED를 {state}로 켭니다/끕니다.")
        GPIO.output(self.pin_led_second_floor, state)        

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
        self._heater_update(self.heater_state)

    def get_heater_state(self) :
        '''히터의 상태를 반환하는 함수 (GPIO.HIGH 혹은 GPIO.LOW)'''
        # TEST : get_heater_state 실제 작동 테스트
        return self.heater_state

    def _heater_update(self, state):
        '''주어진 state에 맞게 히터를 끄거나 켜는 함수'''
        # TEST : _heater_update 실제 작동 테스트
        print(f"[set_heater_state] : 히터를 {state}로 켭니다/끕니다.")
        GPIO.output(self.pin_heater, state)
        print("에베베베")