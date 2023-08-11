import RPi.GPIO as GPIO
# pip install Adafruit_DHT로 DHT 온습도센서 사용 모듈을 설치
import Adafruit_DHT
import asyncio
import spidev
import time
from datetime import datetime
import picamera
from PIL import Image
from io import BytesIO
import board
import base64

# 핀 배치들을 변수로 저장해둠
pin_led_first_floor = 26
pin_led_second_floor = 19
pin_heater = 13
pin_pump = 6


pin_dhts = [21,20,16,12] # [0] ; 21로 나중에 바꾸기


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
    def __init__(self, user_set_min_temp=18):
        '''
        클래스 초기화하며 서버에서 저장된 마지막 사용자설정상태를 받아 self.user_set_변수로 저장함
        - user_set_min_temp : 사용자가 설정한 최저온도
        - user_set_on_time : 사용자가 설정한 불 켜는 시각
        - user_set_off_time : 사용자가 설정한 불 끄는 시각
        '''
        
        self.temperature = 0
        self.humidity = 0
        self.water_level = 0

        # spi 기본 설정
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 1000000

        #  카메라 관련
        self.camera = picamera.PiCamera()
        self.stream = BytesIO()
        
        # 사용자의 설정값
        self.user_set_min_temp = user_set_min_temp
        # TODO: 테스트 끝나면 풀기
        # self.on_time = user_set_on_time
        # self.off_time = user_set_off_time
        self.start_device()
        

    def check_state_integrity(self, state):
        '''state가 허용된 값인 GPIO.HIGH 혹은 GPIO.LOW 둘 중 하나의 값인지 무결성을 검증하는 함수'''
        if state != GPIO.HIGH and state != GPIO.LOW :
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
        GPIO.setup(pin_pump, GPIO.OUT)
        # 예시코드들에서 온습도센서핀은 GPIO 설정 안해주는것 같음
        # for pin in pin_dhts:
        #     GPIO.setup(pin, GPIO.IN)
        
        # 출력 핀들의 초기 출력모드 설정
        self.led_first_state = GPIO.HIGH
        self.led_second_state = GPIO.HIGH
        self.heater_state = GPIO.HIGH
        self.pump_state = GPIO.HIGH

        # 출력 핀들의 초기 출력모드에 따라서 실제 장치들을 켬
        self._heater_update()
        self._led_first_update()
        self._led_second_update()
        self._pump_update()

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
        print("[hardware.measure_temp_and_humidity() 실행됨]")
        humidities = list()
        temperatures = list()
        humid_count = 0
        temp_count = 0
        sensor_type = Adafruit_DHT.DHT11
        for i, sensor in enumerate(pin_dhts[0:1]):
            print(f" {i+1}번 센서 : ", end='')
            print()
            # 측정 시도. 타이밍에 민감한 작업이기 때문에 실패시 2초 기다리고 재측정함. 개당 15까지 측정함
            humid, temp = Adafruit_DHT.read_retry(sensor_type, pin_dhts[i], retries=15)
            if humid is not None :
                humidities.append(humid)
                humid_count += 1
                print(f"    humid : {humid:.3f}")
            else :
                print(f"    humid : Failed (None)")
            if temp is not None:
                temperatures.append(temp)
                temp_count += 1
                print(f"    temp : {temp:.3f}")
            else :
                print(f"    temp : Failed (None)")
        
        # 측정값이 하나도 없으면
        if humid_count == 0:
            print('온습도센서로 측정한 습도값이 없습니다!')
        else :
            self.humidity = sum(humidities) / humid_count
        
        if temp_count == 0:
            print('온습도센서로 측정한 온도값이 없습니다!')
        else :
            self.temperature = sum(temperatures) / temp_count
            
    def measure_water_level(self)->None :
        '''3층 물통 수위 측정해 self.water_level 값을 갱신하는 함수'''
        # TODO : measure_water_level 아날로그 변환 식 제대로 작성하기
        print("[hardware.measure_water_level() 실행됨]")
        adc = self.spi.xfer2([1, (8+ 0) << 4, 0])
        adc_out = ((adc[1]&3) << 8 ) + adc[2]
        a_volt = 3.3 * adc_out / 1024
        print(f"volt : {a_volt}")
        self.water_level = self.adc_to_water_level(a_volt)
        
    def adc_to_water_level(self, a_volt):
        '''수위센서에서 읽은 analog volt값을 수위 cm으로 환산하는 함수'''
        # adc_value 리턴한건 그냥 데이터 반환이 필요해서 한거임
        return a_volt
        # TODO(정수) : 수위센서 adc -> cm 환산 함수 실험 및 실측을 통해 근사식 작성하기

    def set_pump_state(self, state) :
        '''
        펌프의 상태 self.pump_state를 지정하고 그에 맞게 펌프를 켜거나 끄는 함수
        - state : 설정할 펌프의 상태 (GPIO.HIGH/GPIO.LOW)
         * 허용되지 않은 값이 state로 입력될 경우 예외를 raise함
        -> return None
        '''
        # 인자로 주어진 state의 무결성 검증 - 결함 있으면 에러 raise하여 backend단에서 처리하게 함.
        try :
            self.check_state_integrity(state)
        except Exception as e :
            raise e
    
        print(f"[set_pump_state] : 펌프 상태를 {state}로 설정합니다")
        self.pump_state = state
        self._pump_update()        

    def set_led_states(self, state:list) :
        '''
        전등의 self.pump_state를 지정하고 그에 맞게 펌프를 켜거나 끄는 함수
        - state : 설정할 펌프의 상태 (GPIO.HIGH/GPIO.LOW)
         * 허용되지 않은 값이 state로 입력될 경우 예외를 raise함
        -> return None
        '''
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
        # 인자로 주어진 state의 무결성 검증 - 결함 있으면 에러 raise하여 backend단에서 처리하게 함.
        try :
            self.check_state_integrity(state)
        except Exception as e :
            raise e
    
        print(f"[set_heater_state] : 히터 상태를 {state}로 설정합니다")
        self.heater_state = state
        self._heater_update()
      
    def set_min_temp(self, _min_temp):
        print(f"[hardware.set_min_temp] : 설정 최저 온도를 {_min_temp}로 설정합니다")
        self.min_temp = _min_temp
  
    def set_on_time(self, _on_time):
        print(f"[hardware.set_on_time] : 전등을 킬 시각을 {_on_time}로 설정합니다")
        self.on_time = _on_time
  
    def set_off_time(self, _off_time):
        print(f"[hardware.set_off_time] : 전등을 끌 시각을 {_off_time}로 설정합니다")
        self.off_time = _off_time

    def get_temperature(self):
        return self.temperature
    
    def get_humidity(self):
        return self.humidity

    def get_pump_state(self):
        '''펌프 작동 상태 반환하는 함수 (GPIO.HIGH 혹은 GPIO.LOW)'''
        return self.pump_state

    def get_water_level(self) -> float:
        return self.water_level


    def get_light_state(self)->list :
        '''1층과 2층 LED 전원 상태를 얻어오는 함수 [GPIO.HIGH/GPIO.LOW, GPIO.HIGH/GPIO.LOW]'''
        return [self.led_first_state, self.led_second_state]

    
    def get_heater_state(self) :
        '''히터의 상태를 반환하는 함수 (GPIO.HIGH 혹은 GPIO.LOW)'''
        return self.heater_state

    def get_image(self, save_to_file = False):
        '''
        사진을 찍어 base64로 인코딩한 데이터를 리턴함.
        -save_to_file : True로 설정되면 f"./captured_images/datetime.now().strftime('%Y.%m.%d %H:%M:%S').jpeg"로 파일을 저장
        '''
        print("[hardware.get_image() 실행됨]")
        
        photo_width = 600
        photo_height = 600
        self.camera.capture(self.stream, format='jpeg')
        self.stream.seek(0)
        if save_to_file == True :
            with Image.open(self.stream) as img : 
                image_path = './captured_images/'
                image_filename = f"{datetime.now().strftime('%Y.%m.%d %H:%M:%S')}.jpeg"
                img.save(image_path + image_filename)
        self.stream.seek(0)
        encoded_image = base64.b64encode(self.stream.getvalue()).decode("utf-8")
        return encoded_image


    def _pump_update(self):
        '''현재 self.pump_state에 맞게 펌프를 끄거나 켜는 함수'''
        print(f"[_pump_update] : 펌프를 {self.pump_state}로 켭니다/끕니다.")
        GPIO.output(pin_pump, self.pump_state)

    def _heater_update(self):
        print(f"[_heater_update] : 펌프를 {self.pump_state}로 켭니다/끕니다.")    
        GPIO.output(pin_heater, self.heater_state)
        

    def _led_first_update(self):
        print(f"[_led_first_update] : 1층 LED를 {self.led_first_state}로 켭니다/끕니다.")
        GPIO.output(pin_led_first_floor, self.led_first_state)
        
    def _led_second_update(self):
        print(f"[_led_second_update] : 2층 LED를 {self.led_second_state}로 켭니다/끕니다.")
        GPIO.output(pin_led_second_floor, self.led_second_state)        


if __name__ == '__main__':
        d = smartFarm_Device()
