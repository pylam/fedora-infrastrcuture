<?php
/*
Plugin Name: FAS Authentication
Plugin URL: http://fedoraproject.org
Description: FAS Authentication integration plugin
Version: 0.1.0
Author: Fedora Infrastructure Team
Author URI: http://fedoraproject.org/wiki/Infrastructure
*/

// overriding wp_authenticate
if(!function_exists('wp_authenticate')) :

// let's disable a few things
add_action('lost_password', 'disable_function');
add_action('retrieve_password', 'disable_function');
add_action('password_reset', 'disable_function');


/*
 * Configuration Options
 */
function fasauth_config(){

	$config['fas_json_url'] 		= 'http://publictest3.fedoraproject.org/accounts/json/person_by_username?tg_format=json';
	$config['fas_redir_pass_reset'] = 'https://admin.fedoraproject.org/accounts/user/resetpass';
	$config['fas_email_domain'] 	= 'fedoraproject.org';

	return $config;
}

/*
 * FAS Authentication
 */ 
function wp_authenticate($username, $password) {

	$config = fasauth_config();

	$username = sanitize_user($username);

	$ch = curl_init();
	curl_setopt($ch, CURLOPT_URL, $config['fas_json_url']);
	curl_setopt($ch, CURLOPT_POST, 1);
	curl_setopt($ch, CURLOPT_USERAGENT, "Auth_FAS 0.9");
	curl_setopt($ch, CURLOPT_POSTFIELDS, "username=".urlencode($username)."&user_name=".urlencode($username)."&password=".urlencode($password)."&login=Login");                            
	curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
	curl_setopt($ch, CURLOPT_VERBOSE, 1);
	$fasuserdata = json_decode(curl_exec($ch), true);
	curl_close ($ch);

	// fas login successful
	if (isset($fasuserdata["success"]) && $fasuserdata['person']['status'] == 'active') {

		// check minimum requirements
		if (check_login_requirement($fasuserdata) !== true) {
			return new WP_Error('fasauth_min_requirement', __('<strong>Error</strong>: You do not meet minimum requirements to login.'));		
		}

		// let's check wp db for user
		$user = get_userdatabylogin($username);

		// user not found, let's create db entry for it
		if ( !$user || ($user->user_login != $username) ) {			
			$user_id = create_wp_user($username);
			if (!$user_id) {
				return new WP_Error('fasauth_create_wp_user', __('<strong>Error</strong>: Unable to create account. Please contact the webmaster.'));		
			}
			
			return new WP_User($user_id);
		}

		// all good, let go on
		return new WP_User($user->ID);
		
	} else {
		return new WP_Error('fasauth_wrong_credentials', __('<strong>Error</strong>: FAS login unsuccessful.'));
	}
}

/*
 * Creates user in wp db
 */ 
function create_wp_user($username) {

	$config = fasauth_config();

	$password = '';
	require_once(WPINC . DIRECTORY_SEPARATOR . 'registration.php');
	return wpmu_create_user($username, $password, $username.'@'.$config['fas_email_domain']);
}

/*
* Used to disable certain login functions, e.g. retrieving a
* user's password.
*/
function disable_function() {
	die('Feature disabled.');
}

/*
*  checks minimum login requirements
*/
function check_login_requirement($user) {

	$groups = $user["person"]["approved_memberships"];
	//echo "Group: ". print_r($groups);

	// checking other group memberships
	$match = 0;
	$in_cla_done = false;
	for ($i = 0, $cnt = count($groups); $i < $cnt; $i++) {
		// user must be in cla
		if ($groups[$i]["name"] == "cla_done") {
			$in_cla_done = true;
		}

		// keep count of anything non-cla
		if (!preg_match('/^cla_/', $groups[$i]["name"])) {
			$match++;
		}
	}

	// yay! more than in 1 non-cla group
	if ($match > 0 && $in_cla_done) {
		return true;
	}

	// requirements not met
	return false;
}

endif;

?>
