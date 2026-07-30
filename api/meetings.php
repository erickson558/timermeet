<?php
header('Content-Type: application/json; charset=UTF-8');

$storageDirectory = dirname(__DIR__) . DIRECTORY_SEPARATOR . 'data';
$storageFile = $storageDirectory . DIRECTORY_SEPARATOR . 'meetings.json';

ensureStorage($storageDirectory, $storageFile);

$method = isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : 'GET';

if ($method === 'GET') {
    respond(200, array(
        'ok' => true,
        'meetings' => readMeetings($storageFile),
    ));
}

if ($method === 'POST') {
    $rawPayload = file_get_contents('php://input');
    $payload = json_decode($rawPayload ? $rawPayload : '', true);

    if (!is_array($payload) || !isset($payload['meetings']) || !is_array($payload['meetings'])) {
        respond(400, array(
            'ok' => false,
            'message' => 'Invalid meetings payload.',
        ));
    }

    if (count($payload['meetings']) > 2000) {
        respond(400, array(
            'ok' => false,
            'message' => 'Too many meetings in a single payload.',
        ));
    }

    $meetings = array();
    foreach ($payload['meetings'] as $meeting) {
        $meetings[] = normalizeMeeting($meeting);
    }

    if (!writeMeetings($storageFile, $meetings)) {
        respond(500, array(
            'ok' => false,
            'message' => 'Could not write meetings file.',
        ));
    }

    respond(200, array(
        'ok' => true,
        'meetings' => $meetings,
    ));
}

respond(405, array(
    'ok' => false,
    'message' => 'Method not allowed.',
));

function ensureStorage($directory, $file)
{
    if (!is_dir($directory) && !mkdir($directory, 0777, true) && !is_dir($directory)) {
        respond(500, array(
            'ok' => false,
            'message' => 'Could not create storage directory.',
        ));
    }

    if (!file_exists($file) && file_put_contents($file, "[]\n", LOCK_EX) === false) {
        respond(500, array(
            'ok' => false,
            'message' => 'Could not initialize storage file.',
        ));
    }
}

function readMeetings($file)
{
    $handle = fopen($file, 'c+');
    if ($handle === false) {
        return array();
    }

    flock($handle, LOCK_SH);
    rewind($handle);
    $contents = stream_get_contents($handle);
    flock($handle, LOCK_UN);
    fclose($handle);

    if ($contents === false || trim($contents) === '') {
        return array();
    }

    $decoded = json_decode($contents, true);
    if (!is_array($decoded)) {
        return array();
    }

    $meetings = array();
    foreach ($decoded as $meeting) {
        if (is_array($meeting)) {
            $meetings[] = normalizeMeeting($meeting);
        }
    }

    return array_values($meetings);
}

function writeMeetings($file, $meetings)
{
    $json = json_encode($meetings, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    if ($json === false) {
        return false;
    }

    $handle = fopen($file, 'c+');
    if ($handle === false) {
        return false;
    }

    if (!flock($handle, LOCK_EX)) {
        fclose($handle);
        return false;
    }

    $success = true;

    if (!ftruncate($handle, 0)) {
        $success = false;
    }

    rewind($handle);

    if ($success && fwrite($handle, $json . PHP_EOL) === false) {
        $success = false;
    }

    fflush($handle);
    flock($handle, LOCK_UN);
    fclose($handle);

    return $success;
}

function normalizeMeeting($meeting)
{
    if (!is_array($meeting)) {
        return array();
    }

    return array(
        'id' => trim((string)(isset($meeting['id']) ? $meeting['id'] : '')),
        'workName' => trim((string)(isset($meeting['workName']) ? $meeting['workName'] : '')),
        'title' => trim((string)(isset($meeting['title']) ? $meeting['title'] : '')),
        'datetime' => trim((string)(isset($meeting['datetime']) ? $meeting['datetime'] : '')),
        'reminderMinutes' => max(1, (int)(isset($meeting['reminderMinutes']) ? $meeting['reminderMinutes'] : 15)),
        'soundProfile' => trim((string)(isset($meeting['soundProfile']) ? $meeting['soundProfile'] : 'soft')),
        'teamsUrl' => trim((string)(isset($meeting['teamsUrl']) ? $meeting['teamsUrl'] : '')),
        'notes' => trim((string)(isset($meeting['notes']) ? $meeting['notes'] : '')),
        'recurrenceType' => normalizeRecurrenceType(isset($meeting['recurrenceType']) ? $meeting['recurrenceType'] : 'none'),
        'seriesId' => trim((string)(isset($meeting['seriesId']) ? $meeting['seriesId'] : '')),
        'occurrenceIndex' => max(1, (int)(isset($meeting['occurrenceIndex']) ? $meeting['occurrenceIndex'] : 1)),
        'seriesSize' => max(1, (int)(isset($meeting['seriesSize']) ? $meeting['seriesSize'] : 1)),
        'reminderSent' => !empty($meeting['reminderSent']),
        'startSent' => !empty($meeting['startSent']),
        'createdAt' => trim((string)(isset($meeting['createdAt']) ? $meeting['createdAt'] : '')),
        'updatedAt' => trim((string)(isset($meeting['updatedAt']) ? $meeting['updatedAt'] : '')),
    );
}

function normalizeRecurrenceType($recurrenceType)
{
    $normalized = trim((string)$recurrenceType);
    $allowed = array('none', 'daily', 'weekdays', 'weekly', 'biweekly', 'monthly');

    if (!in_array($normalized, $allowed, true)) {
        return 'none';
    }

    return $normalized;
}

function respond($statusCode, $payload)
{
    http_response_code($statusCode);
    echo json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    exit;
}
