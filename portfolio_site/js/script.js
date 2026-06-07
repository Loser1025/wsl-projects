// JavaScriptの基本構造
console.log('ポートフォリオサイトが読み込まれました');

// ボタンのクリックイベント
const contactButton = document.getElementById('contactButton');
if (contactButton) {
    contactButton.addEventListener('click', function() {
        alert('お問い合わせページに移動します');
        window.location.href = 'contact.html';
    });
}

// プロジェクト詳細ボタンのクリックイベント
const projectButtons = document.querySelectorAll('.project button');
projectButtons.forEach(button => {
    button.addEventListener('click', function() {
        alert('プロジェクト詳細ページに移動します');
        window.location.href = 'project_detail.html';
    });
});
