PluginsAPI.Map.willAddControls([
    	'watershed/build/Watershed.js',
    	'watershed/build/Watershed.css'
	], function(args, Watershed){
	var tasks = [];
	var ids = {};

	for (var i = 0; i < args.tiles.length; i++){
		var task = args.tiles[i].meta.task;
		if (!ids[task.id]){
			tasks.push(task);
			ids[task.id] = true;
		}
	}

	if (tasks.length === 1){
		args.map.addControl(new Watershed({map: args.map, tasks: tasks}));
	}
});
