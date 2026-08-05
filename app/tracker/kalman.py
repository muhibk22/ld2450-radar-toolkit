"""
2D Constant-Velocity Kalman Filter for Position Smoothing and Velocity Estimation.
"""

import numpy as np

class KalmanFilter2D:
    """
    Kalman Filter for 2D position (x, y) and velocity (vx, vy) tracking.
    State vector: [x, y, vx, vy]^T
    Measurement vector: [x, y]^T
    """

    def __init__(self, dt: float = 0.05, process_noise: float = 2.0, measurement_noise: float = 15.0):
        self.dt = dt
        
        # State vector: [x, y, vx, vy]^T
        self.x = np.zeros((4, 1), dtype=np.float64)
        
        # State covariance matrix P
        self.P = np.eye(4, dtype=np.float64) * 500.0
        
        # State transition matrix F
        self.F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=np.float64)
        
        # Measurement matrix H
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ], dtype=np.float64)
        
        # Measurement covariance R (suppresses raw coordinate jitter)
        self.R = np.eye(2, dtype=np.float64) * (measurement_noise ** 2)
        
        # Process noise covariance Q
        self.process_noise = process_noise
        q_pos = 0.5 * (dt ** 2) * process_noise
        q_vel = dt * process_noise
        self.Q = np.array([
            [q_pos**2, 0, q_pos*q_vel, 0],
            [0, q_pos**2, 0, q_pos*q_vel],
            [q_pos*q_vel, 0, q_vel**2, 0],
            [0, q_pos*q_vel, 0, q_vel**2]
        ], dtype=np.float64)

    def set_dt(self, dt: float):
        """Updates matrices F and Q for dynamic variable time-steps."""
        self.dt = dt
        self.F[0, 2] = dt
        self.F[1, 3] = dt
        
        q_pos = 0.5 * (dt ** 2) * self.process_noise
        q_vel = dt * self.process_noise
        self.Q = np.array([
            [q_pos**2, 0, q_pos*q_vel, 0],
            [0, q_pos**2, 0, q_pos*q_vel],
            [q_pos*q_vel, 0, q_vel**2, 0],
            [0, q_pos*q_vel, 0, q_vel**2]
        ], dtype=np.float64)

    def init_state(self, pos_x: float, pos_y: float):
        """Initializes state vector with initial measured position."""
        self.x = np.array([[pos_x], [pos_y], [0.0], [0.0]], dtype=np.float64)
        self.P = np.eye(4, dtype=np.float64) * 10.0

    def predict(self) -> np.ndarray:
        """Predicts next state using motion model."""
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x

    def update(self, pos_x: float, pos_y: float):
        """Updates state estimate with new measurement."""
        z = np.array([[pos_x], [pos_y]], dtype=np.float64)
        y = z - (self.H @ self.x)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        
        self.x = self.x + (K @ y)
        I = np.eye(4, dtype=np.float64)
        self.P = (I - K @ self.H) @ self.P

    @property
    def position(self) -> tuple[float, float]:
        """Returns estimated (x, y) position in mm."""
        return float(self.x[0, 0]), float(self.x[1, 0])

    @property
    def velocity(self) -> tuple[float, float]:
        """Returns estimated (vx, vy) velocity in mm/s."""
        return float(self.x[2, 0]), float(self.x[3, 0])
