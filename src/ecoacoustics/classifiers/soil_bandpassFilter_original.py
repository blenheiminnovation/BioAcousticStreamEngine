import numpy as np
import scipy.signal
import scipy.io.wavfile
import matplotlib.pyplot as plt

def bandpass(data: np.ndarray, edges: list, sample_rate: float, poles: int = 5):
    sos = scipy.signal.butter(poles, edges, 'bandpass', fs=sample_rate, output='sos')
    filtered_data = scipy.signal.sosfiltfilt(sos, data)
    return filtered_data

sample_rate, data = scipy.io.wavfile.read('batAudio/Eptser_A-20180530_213232.wav')


times = np.arange(len(data))/sample_rate

filtered = bandpass(data, [30000, 80000], sample_rate) # i have changed it from 50000

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3), sharex=True, sharey=True)
ax1.plot(times, data)
ax1.set_title("Original Signal")
ax1.margins(0, .1)
ax1.grid(alpha=.5, ls='--')
ax2.plot(times, filtered)
ax2.set_title("Band-Pass Filter (20khz-50khz)")
ax2.grid(alpha=.5, ls='--')
plt.tight_layout()
plt.show()


# Convert to 16 integers
scipy.io.wavfile.write('filterTests/Epster_filtered.wav5', sample_rate, filtered.astype(np.int16))