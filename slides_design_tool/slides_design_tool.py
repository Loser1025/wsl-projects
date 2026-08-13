import os
import json
import math
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pickle

class GoogleSlidesTool:
    """
    Googleスライドのデザイン編集を網羅的に行うためのAIエージェント向け究極ツールクラス。
    """
    def __init__(self, credentials_path='credentials.json', token_path='token.pickle', scopes=None):
        if scopes is None:
            self.scopes = ['https://www.googleapis.com/auth/presentations', 'https://www.googleapis.com/auth/drive']
        else:
            self.scopes = scopes
        
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = self._authenticate()

    def _authenticate(self):
        """認証処理。サービスアカウントまたはOAuth2をサポート。"""
        creds = None
        if os.path.exists(self.token_path):
            with open(self.token_path, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                try:
                    if os.path.exists(self.credentials_path):
                        with open(self.credentials_path, 'r') as f:
                            data = json.load(f)
                        if data.get('type') == 'service_account':
                            creds = service_account.Credentials.from_service_account_file(
                                self.credentials_path, scopes=self.scopes)
                        else:
                            flow = InstalledAppFlow.from_client_secrets_file(
                                self.credentials_path, self.scopes)
                            creds = flow.run_local_server(port=0)
                            with open(self.token_path, 'wb') as token:
                                pickle.dump(creds, token)
                except Exception as e:
                    print(f"Authentication Error: {e}")
                    raise
        return build('slides', 'v1', credentials=creds)

    def get_presentation(self, presentation_id):
        """スライド情報を取得。"""
        try:
            return self.service.presentations().get(presentationId=presentation_id).execute()
        except HttpError as e:
            print(f"Error getting presentation: {e}")
            return None

    def batch_update(self, presentation_id, requests):
        """一括更新。"""
        if not requests: return None
        try:
            return self.service.presentations().batchUpdate(
                presentationId=presentation_id, body={'requests': requests}).execute()
        except HttpError as e:
            print(f"Error in batch update: {e}")
            return None

    # --- 1. テキスト & スタイル ---

    def replace_text(self, presentation_id, old_text, new_text):
        """全体テキスト置換。"""
        return self.batch_update(presentation_id, [{
            'replaceAllText': {'replaceText': new_text, 'containsText': {'text': old_text, 'matchCase': False}}
        }])

    def update_text_style(self, presentation_id, object_id, font_size=None, bold=None, italic=None, color_rgb=None, font_family=None):
        """テキストスタイル。color_rgb: (r, g, b) 0.0-1.0"""
        style = {}
        fields = []
        if font_size: style['fontSize'] = {'magnitude': font_size, 'unit': 'PT'}; fields.append('fontSize')
        if bold is not None: style['bold'] = bold; fields.append('bold')
        if italic is not None: style['italic'] = italic; fields.append('italic')
        if font_family: style['fontFamily'] = font_family; fields.append('fontFamily')
        if color_rgb:
            style['foregroundColor'] = {'opaqueColor': {'rgbColor': {'red': color_rgb[0], 'green': color_rgb[1], 'blue': color_rgb[2]}}}
            fields.append('foregroundColor')
        return self.batch_update(presentation_id, [{'updateTextStyle': {'objectId': object_id, 'style': style, 'fields': ','.join(fields)}}])

    def update_paragraph_style(self, presentation_id, object_id, alignment='START'):
        """段落揃え: START, CENTER, END, JUSTIFIED"""
        return self.batch_update(presentation_id, [{
            'updateParagraphStyle': {'objectId': object_id, 'style': {'alignment': alignment}, 'fields': 'alignment'}
        }])

    # --- 2. 図形 & 配置 & グループ化 ---

    def create_shape(self, presentation_id, slide_id, shape_type='RECTANGLE', x=100, y=100, w=100, h=100):
        """汎用図形作成。RECTANGLE, ELLIPSE, TRIANGLE, etc."""
        obj_id = f"shape_{os.urandom(4).hex()}"
        request = {
            'createShape': {
                'objectId': obj_id, 'shapeType': shape_type,
                'elementProperties': {
                    'pageObjectId': slide_id,
                    'size': {'width': {'magnitude': w, 'unit': 'PT'}, 'height': {'magnitude': h, 'unit': 'PT'}},
                    'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': x, 'translateY': y, 'unit': 'PT'}
                }
            }
        }
        self.batch_update(presentation_id, [request])
        return obj_id

    def create_text_box(self, presentation_id, slide_id, x=100, y=100, w=300, h=50, text=""):
        """テキストボックス作成。"""
        obj_id = self.create_shape(presentation_id, slide_id, 'TEXT_BOX', x, y, w, h)
        if text:
            self.batch_update(presentation_id, [{'insertText': {'objectId': obj_id, 'text': text}}])
        return obj_id

    def group_objects(self, presentation_id, object_ids):
        """複数のオブジェクトをグループ化。"""
        group_id = f"group_{os.urandom(4).hex()}"
        self.batch_update(presentation_id, [{'groupObjects': {'childrenObjectIds': object_ids, 'groupObjectId': group_id}}])
        return group_id

    def ungroup_objects(self, presentation_id, object_ids):
        """グループ化を解除。"""
        return self.batch_update(presentation_id, [{'ungroupObjects': {'objectIds': object_ids}}])

    def change_shape_color(self, presentation_id, object_id, r, g, b):
        """図形の塗りつぶし色。"""
        return self.batch_update(presentation_id, [{
            'updateShapeProperties': {
                'objectId': object_id, 'fields': 'shapeBackgroundFill.solidFill.color',
                'shapeProperties': {'shapeBackgroundFill': {'solidFill': {'color': {'rgbColor': {'red': r, 'green': g, 'blue': b}}}}}
            }
        }])

    def update_border(self, presentation_id, object_id, weight=1, color_rgb=(0,0,0), dash='SOLID'):
        """枠線設定。"""
        return self.batch_update(presentation_id, [{
            'updateShapeProperties': {
                'objectId': object_id, 'fields': 'outline.outlineFill.solidFill.color,outline.weight,outline.dashStyle',
                'shapeProperties': {
                    'outline': {
                        'weight': {'magnitude': weight, 'unit': 'PT'}, 'dashStyle': dash,
                        'outlineFill': {'solidFill': {'color': {'rgbColor': {'red': color_rgb[0], 'green': color_rgb[1], 'blue': color_rgb[2]}}}}
                    }
                }
            }
        }])

    def transform_object(self, presentation_id, object_id, tx, ty, sx=1, sy=1, rotation=0):
        """座標変換（移動、スケール、回転）。rotationは度。"""
        theta = rotation * math.pi / 180.0
        request = {
            'updatePageElementTransform': {
                'objectId': object_id, 'applyMode': 'ABSOLUTE',
                'transform': {
                    'scaleX': sx * math.cos(theta), 'shearX': sx * math.sin(theta),
                    'shearY': -sy * math.sin(theta), 'scaleY': sy * math.cos(theta),
                    'translateX': tx, 'translateY': ty, 'unit': 'PT'
                }
            }
        }
        return self.batch_update(presentation_id, [request])

    def update_z_order(self, presentation_id, object_id, command='BRING_TO_FRONT'):
        """重なり順: BRING_TO_FRONT, BRING_FORWARD, SEND_BACKWARD, SEND_TO_BACK"""
        return self.batch_update(presentation_id, [{'updatePageElementsZOrder': {'pageElementObjectIds': [object_id], 'operation': command}}])

    # --- 3. 画像 & 背景 & ライン ---

    def insert_image(self, presentation_id, slide_id, image_url, x=100, y=100, w=200, h=200):
        return self.batch_update(presentation_id, [{
            'createImage': {
                'url': image_url,
                'elementProperties': {'pageObjectId': slide_id, 'size': {'width': {'magnitude': w, 'unit': 'PT'}, 'height': {'magnitude': h, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': x, 'translateY': y, 'unit': 'PT'}}
            }
        }])

    def create_line(self, presentation_id, slide_id, line_type='STRAIGHT', x=100, y=100, w=100, h=100):
        """ライン作成: STRAIGHT, BENT, CURVED"""
        obj_id = f"line_{os.urandom(4).hex()}"
        self.batch_update(presentation_id, [{
            'createLine': {
                'objectId': obj_id, 'lineCategory': line_type,
                'elementProperties': {'pageObjectId': slide_id, 'size': {'width': {'magnitude': w, 'unit': 'PT'}, 'height': {'magnitude': h, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': x, 'translateY': y, 'unit': 'PT'}}
            }
        }])
        return obj_id

    def set_slide_background(self, presentation_id, slide_id, r=None, g=None, b=None, image_url=None):
        """背景色または背景画像の設定。"""
        prop = {}
        if image_url: prop['stretchedPictureFill'] = {'contentUrl': image_url}
        elif r is not None: prop['solidFill'] = {'color': {'rgbColor': {'red': r, 'green': g, 'blue': b}}}
        return self.batch_update(presentation_id, [{
            'updatePageProperties': {'objectId': slide_id, 'fields': 'pageBackgroundFill', 'pageProperties': {'pageBackgroundFill': prop}}
        }])

    # --- 4. テーブル操作 ---

    def create_table(self, presentation_id, slide_id, rows, cols, x=100, y=100, w=400, h=200):
        obj_id = f"table_{os.urandom(4).hex()}"
        self.batch_update(presentation_id, [{
            'createTable': {
                'objectId': obj_id, 'rows': rows, 'columns': cols,
                'elementProperties': {'pageObjectId': slide_id, 'size': {'width': {'magnitude': w, 'unit': 'PT'}, 'height': {'magnitude': h, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': x, 'translateY': y, 'unit': 'PT'}}
            }
        }])
        return obj_id

    def update_table_cell(self, presentation_id, table_id, row, col, text=None, bg_color_rgb=None):
        requests = []
        if text: requests.append({'insertText': {'objectId': table_id, 'cellLocation': {'rowIndex': row, 'columnIndex': col}, 'text': text}})
        if bg_color_rgb:
            requests.append({
                'updateTableCellProperties': {
                    'objectId': table_id, 'tableRange': {'location': {'rowIndex': row, 'columnIndex': col}, 'rowSpan': 1, 'columnSpan': 1},
                    'fields': 'tableCellBackgroundFill.solidFill.color',
                    'tableCellProperties': {'tableCellBackgroundFill': {'solidFill': {'color': {'rgbColor': {'red': bg_color_rgb[0], 'green': bg_color_rgb[1], 'blue': bg_color_rgb[2]}}}}}
                }
            })
        return self.batch_update(presentation_id, requests)

    # --- 5. スライド & ユーティリティ ---

    def create_slide(self, presentation_id, layout='BLANK', index=None):
        return self.batch_update(presentation_id, [{'createSlide': {'slideLayoutReference': {'predefinedLayout': layout}, 'insertionIndex': index}}])

    def duplicate_object(self, presentation_id, object_id):
        return self.batch_update(presentation_id, [{'duplicateObject': {'objectId': object_id}}])

    def delete_object(self, presentation_id, object_id):
        return self.batch_update(presentation_id, [{'deleteObject': {'objectId': object_id}}])

    def find_objects(self, presentation_id, search_text=None, object_type=None):
        pres = self.get_presentation(presentation_id)
        if not pres: return []
        results = []
        for slide in pres.get('slides', []):
            for el in slide.get('pageElements', []):
                match = True
                if object_type and object_type not in str(el).upper(): match = False
                text = ""
                if 'shape' in el and 'text' in el['shape']:
                    for te in el['shape']['text'].get('textElements', []):
                        if 'textRun' in te: text += te['textRun'].get('content', '')
                if search_text and search_text not in text: match = False
                if match: results.append({'slideId': slide['objectId'], 'objectId': el['objectId'], 'type': el.get('shape', {}).get('shapeType', 'OTHER'), 'text': text})
        return results

if __name__ == "__main__":
    print("GoogleSlidesTool Ultimate Edition initialized.")
