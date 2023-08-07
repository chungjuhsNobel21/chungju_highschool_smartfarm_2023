from flask import Flask, request, redirect, send_file, render_template, session
from datetime import datetime

app = Flask(__name__)
app.secret_key = '19110'

@app.route('/control/set_temp', methods=['POST'])
def set_temp():
    if request.method == 'POST':
        temp = request.form['temp']

    return render_template('hardware.py', min_temp= temp)


@app.route('/control/set_time_period', methods=['POST'])
def set_time():
    if request.method == 'POST':
        on_time = request.form['turn_on_time']
        off_time = request.form['turn_off_time']

    return render_template('hardware.py', turn_on_time = on_time, turn_off_time = off_time)    
