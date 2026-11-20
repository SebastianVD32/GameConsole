"""One process owns all matches; HTTP threads serve concurrent players."""
import os

bind = f"0.0.0.0:{int(os.environ.get('PORT', '5000'))}"
workers = 1
threads = 16
accesslog = "-"
errorlog = "-"
